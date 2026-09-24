/**
 * dramaclip:// 本地媒体预览协议的围栏与有界读（协议注册在 main/index.ts）。
 *
 * 为什么要有围栏：该协议带 bypassCSP/supportFetchAPI 特权，渲染层一旦被注入
 * 脚本，无围栏的处理器就是「读本机任意文件」的出口。放行范围只有两族——
 * dataDir（成品/封面/试听缓存全在它下面）与已登记项目的素材根（源片预览
 * PlayerCard 要播任意用户目录里的视频，围不死，只能圈到素材根）。
 *
 * 内存上有界：Range 响应用流式 body 按块定位读（内容头仍覆盖完整请求区间——
 * 截断的 206 会被 Chromium 媒体栈判死）；未带 Range 的整读只服务封面/试听这类
 * 小文件，超上限直接拒绝——宁可不打这个预览，也不把多 GB 源片整块拉进 RAM。
 */
import { promises as fsPromises } from 'node:fs';
import type { FileHandle } from 'node:fs/promises';
import path from 'node:path';

/** 预览扩展名白名单（同时是响应类型表）：名单外一律 403，不留 octet-stream 出口。 */
const CONTENT_TYPES: Record<string, string> = {
  mp4: 'video/mp4',
  webm: 'video/webm',
  mov: 'video/quicktime',
  mkv: 'video/x-matroska',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  mp3: 'audio/mpeg',
  wav: 'audio/wav',
};

/** 未带 Range 的整读上限：封面 jpg 与试听 wav 都在 MB 级，1GiB 已是极限余量。 */
const MAX_WHOLE_READ_BYTES = 1024 * 1024 * 1024;
/** 流式 body 的单块尺寸：内存占用与文件大小无关，靠分块读而非截断响应。 */
const STREAM_CHUNK_BYTES = 4 * 1024 * 1024;
/** 素材根缓存时长：新导入项目的源片预览靠 miss 强刷兜底，不追求实时。 */
const ROOTS_TTL_MS = 60_000;

export type PreviewRootsGetter = (forceRefresh: boolean) => Promise<readonly string[]>;

export function decodePreviewPath(url: string): string | null {
  try {
    const pathname = new URL(url).pathname.replace(/^\/+/, '');
    if (pathname === '') return null;
    return decodeURIComponent(pathname).replaceAll('\\', '/');
  } catch {
    return null;
  }
}

export function isWithinRoots(filePath: string, roots: readonly string[]): boolean {
  const target = path.resolve(filePath);
  for (const root of roots) {
    const rel = path.relative(path.resolve(root), target);
    // rel=='' 是根目录本身（是目录不是预览文件）；'..' 前缀与绝对路径都是越界。
    // win32 下 path.relative 自身按大小写不敏感比较，无需手动归一。
    if (rel !== '' && !rel.startsWith('..') && !path.isAbsolute(rel)) return true;
  }
  return false;
}

export function previewContentType(filePath: string): string | null {
  const ext = filePath.split('.').pop()?.toLowerCase() ?? '';
  return CONTENT_TYPES[ext] ?? null;
}

/** 解析 Range 头：null=未带；'unsatisfiable'=越界（回 416）；否则返回请求区间。
 * maxChunkBytes 默认不钳：2026-09-24 真媒体栈实测，Chromium video 对「比请求短」的
 * 首个 206 直接判死（error code=4，且不再发后续 Range）——截断响应喂不了媒体栈，
 * 内存有界靠流式 body（streamSpan），不靠钳窗口。显式传参仍可用于非媒体场景。 */
export function parseRange(
  header: string | null,
  size: number,
  maxChunkBytes: number = Number.POSITIVE_INFINITY,
): { start: number; end: number } | 'unsatisfiable' | null {
  if (header === null) return null;
  const match = /bytes=(\d+)-(\d*)/.exec(header);
  if (match === null) return 'unsatisfiable';
  const start = Number(match[1]);
  if (start >= size) return 'unsatisfiable';
  const requested = match[2] === '' ? size - 1 : Math.min(Number(match[2]), size - 1);
  return { start, end: Math.min(requested, start + maxChunkBytes - 1) };
}

/** 素材根供给：dataDir 恒在；source_path 族经 RPC 取，60s TTL + 失败退回 dataDir 围栏。 */
export function createPreviewRoots(
  fetchSourceRoots: () => Promise<readonly string[]>,
  dataDir: string,
): PreviewRootsGetter {
  let cached: readonly string[] = [dataDir];
  let fetchedAt = 0;
  let inflight: Promise<readonly string[]> | null = null;
  return (forceRefresh: boolean) => {
    if (!forceRefresh && Date.now() - fetchedAt < ROOTS_TTL_MS) return Promise.resolve(cached);
    if (inflight !== null) return inflight;
    inflight = (async () => {
      try {
        cached = [dataDir, ...new Set(await fetchSourceRoots())];
      } catch {
        // 服务未连上/未就绪：退回 dataDir 围栏，成品与封面仍可预览，素材根等下一轮
      }
      fetchedAt = Date.now();
      return cached;
    })();
    void inflight.then(() => { inflight = null; }, () => { inflight = null; });
    return inflight;
  };
}

/** 读文件指定区间（定位读，不整载）。裸 ArrayBuffer 而非 Buffer.allocUnsafe：
 * BodyInit 的类型契约要 Uint8Array<ArrayBuffer>（TS 5.7+ 泛型收紧）；
 * 零填充随即被 fh.read 全量覆写，无脏数据外泄。 */
async function readSpan(
  fh: FileHandle,
  start: number,
  length: number,
): Promise<Uint8Array<ArrayBuffer>> {
  const buffer = new Uint8Array(new ArrayBuffer(length));
  const { bytesRead } = await fh.read(buffer, 0, length, start);
  return buffer.subarray(0, bytesRead);
}

/** 流式 body：按块定位读，内存占用与文件大小无关。
 * 句柄所有权移交流——读完或取消（Chromium 拿完 metadata 就取消整文件 body、
 * 改发新 Range，2026-09-24 探针实测）都负责关闭，不在 finally 里提前关。 */
function streamSpan(fh: FileHandle, start: number, length: number): ReadableStream<Uint8Array> {
  let offset = 0;
  const closeOnce = (): void => {
    void fh.close().catch(() => {
      // 双路径（读完 + 取消）可能都触发；第二次 close 拒绝就吞掉
    });
  };
  return new ReadableStream<Uint8Array>({
    async pull(controller): Promise<void> {
      if (offset >= length) {
        controller.close();
        closeOnce();
        return;
      }
      const want = Math.min(STREAM_CHUNK_BYTES, length - offset);
      const chunk = await readSpan(fh, start + offset, want);
      if (chunk.byteLength === 0) {
        controller.close();
        closeOnce();
        return;
      }
      offset += chunk.byteLength;
      controller.enqueue(chunk);
    },
    cancel(): void {
      closeOnce();
    },
  });
}

function baseHeaders(contentType: string): Record<string, string> {
  return { 'content-type': contentType, 'accept-ranges': 'bytes' };
}

export function createPreviewHandler(getRoots: PreviewRootsGetter) {
  return async (request: Request): Promise<Response> => {
    try {
      return await servePreview(request, getRoots);
    } catch (error) {
      console.error(`[dramaclip] handler 异常: ${String(error)}`);
      return new Response('error', { status: 500 });
    }
  };
}

async function servePreview(
  request: Request,
  getRoots: PreviewRootsGetter,
): Promise<Response> {
  const filePath = decodePreviewPath(request.url);
  if (filePath === null) return new Response('bad url', { status: 400 });
  const stat = await fsPromises.stat(filePath).catch(() => null);
  if (!stat?.isFile()) {
    console.error(`[dramaclip] not found: ${filePath}`);
    return new Response('not found', { status: 404 });
  }
  const contentType = previewContentType(filePath);
  if (contentType === null) {
    console.error(`[dramaclip] 拒绝白名单外类型: ${filePath}`);
    return new Response('forbidden', { status: 403 });
  }
  // 双重围栏：符号链接库（junction 素材根）靠原路径判，穿越/逃逸靠 realpath 判，
  // 两者任一在界内才放行——realpath 不存在时（特殊设备文件等）只信原路径。
  const real = await fsPromises.realpath(filePath).catch(() => null);
  let allowed = isWithinRoots(filePath, await getRoots(false));
  if (!allowed && real !== null) {
    allowed = isWithinRoots(real, await getRoots(true));
  }
  if (!allowed) {
    console.error(`[dramaclip] 拒绝越界路径: ${filePath}`);
    return new Response('forbidden', { status: 403 });
  }
  if (stat.size > MAX_WHOLE_READ_BYTES && request.headers.get('range') === null) {
    console.error(`[dramaclip] 文件超整读上限，拒绝无 Range 预览: ${filePath}`);
    return new Response('too large', { status: 403 });
  }
  const range = parseRange(request.headers.get('range'), stat.size);
  if (range === 'unsatisfiable') return new Response('range not satisfiable', { status: 416 });
  const fh = await fsPromises.open(filePath, 'r');
  if (range === null) {
    // 封面/试听这类小文件整读（上面已按 1GiB 上限拦过）；读完即关句柄。
    try {
      const body = await readSpan(fh, 0, stat.size);
      return new Response(body, {
        headers: { ...baseHeaders(contentType), 'content-length': String(stat.size) },
      });
    } finally {
      await fh.close();
    }
  }
  // 媒体主路径：content 头必须覆盖请求的完整区间——「比请求短」的 206 会被
  // Chromium 媒体栈直接判死（error code=4 且不再续传，2026-09-24 真源片探针实证）；
  // 内存有界靠流式分块 body，不靠截断。句柄所有权移交 streamSpan（读完/取消都关）。
  const length = range.end - range.start + 1;
  return new Response(streamSpan(fh, range.start, length), {
    status: 206,
    headers: {
      ...baseHeaders(contentType),
      'content-length': String(length),
      'content-range': `bytes ${String(range.start)}-${String(range.end)}/${String(stat.size)}`,
    },
  });
}
