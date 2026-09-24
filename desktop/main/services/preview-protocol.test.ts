// @vitest-environment node
/** 预览协议围栏：路径围栏、扩展名白名单、Range 窗口、roots TTL 与处理器端到端。 */
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  createPreviewHandler,
  createPreviewRoots,
  decodePreviewPath,
  isWithinRoots,
  parseRange,
  previewContentType,
} from './preview-protocol';

describe('decodePreviewPath', () => {
  it('编码的绝对路径原样还原（盘符冒号与反斜杠都活得下来）', () => {
    const raw = 'D:\\素材\\第01集.mp4';
    expect(decodePreviewPath(`dramaclip://local/${encodeURIComponent(raw)}`)).toBe(
      'D:/素材/第01集.mp4',
    );
  });

  it('空路径与坏编码返回 null', () => {
    expect(decodePreviewPath('dramaclip://local/')).toBeNull();
    expect(decodePreviewPath('dramaclip://local/%E0%A4%A')).toBeNull();
  });
});

describe('isWithinRoots', () => {
  const root = path.resolve(tmpdir(), 'dc-fence-root');

  it('根内文件放行；穿越出去的兄弟目录与根本身都拒绝', () => {
    expect(isWithinRoots(path.join(root, 'a', 'b.mp4'), [root])).toBe(true);
    expect(isWithinRoots(path.resolve(root, '..', 'escape.mp4'), [root])).toBe(false);
    expect(isWithinRoots(root, [root])).toBe(false);
  });

  it('win32 大小写不敏感：路径大小写不同照样在界内（CI 的 Linux 平台自跳过）', () => {
    if (process.platform !== 'win32') return;
    const variant = root.toUpperCase() === root ? root.toLowerCase() : root.toUpperCase();
    if (variant !== root) {
      expect(isWithinRoots(path.join(variant, 'x.mp4'), [root])).toBe(true);
    }
  });
});

describe('previewContentType / parseRange', () => {
  it('白名单外扩展名（.db/.txt）不给类型——不留 octet-stream 出口', () => {
    expect(previewContentType('a/b/c.mp4')).toBe('video/mp4');
    expect(previewContentType('a/b/state.db')).toBeNull();
    expect(previewContentType('a/b/notes.txt')).toBeNull();
  });

  it('Range：未带头为 null；开放式收在文件尾；显式端点不超尾', () => {
    expect(parseRange(null, 100)).toBeNull();
    expect(parseRange('bytes=0-', 100)).toEqual({ start: 0, end: 99 });
    expect(parseRange('bytes=10-500', 100)).toEqual({ start: 10, end: 99 });
  });

  it('Range：起点越界判 unsatisfiable；窗口上限把长请求钳住', () => {
    expect(parseRange('bytes=100-', 100)).toBe('unsatisfiable');
    expect(parseRange('bytes=0-999', 1000, 300)).toEqual({ start: 0, end: 299 });
  });
});

describe('createPreviewRoots', () => {
  it('TTL 内不重取；force 强刷；取失败退回上一份缓存', async () => {
    let calls = 0;
    const fail = { fail: false };
    const get = createPreviewRoots(() => {
      calls += 1;
      if (fail.fail) return Promise.reject(new Error('服务未连上'));
      return Promise.resolve([`D:/mat-${String(calls)}`]);
    }, 'D:/data');
    expect(await get(false)).toContain('D:/mat-1');
    expect(await get(false)).toContain('D:/mat-1'); // TTL 内复用
    expect(await get(true)).toContain('D:/mat-2'); // 强刷
    fail.fail = true;
    const after = await get(true);
    expect(calls).toBe(3);
    expect(after).toContain('D:/mat-2'); // 失败保留旧围栏
    expect(after).toContain('D:/data');
  });
});

describe('createPreviewHandler 端到端（真实临时文件）', () => {
  function makeFixture() {
    const base = mkdtempSync(path.join(tmpdir(), 'dc-preview-'));
    const inside = path.join(base, 'ep01.mp4');
    writeFileSync(inside, Buffer.alloc(1000, 7));
    const outside = path.join(mkdtempSync(path.join(tmpdir(), 'dc-out-')), 'secret.jpg');
    writeFileSync(outside, Buffer.alloc(10, 1));
    const txt = path.join(base, 'notes.txt');
    writeFileSync(txt, 'x');
    return { base, inside, outside, txt };
  }
  const mediaUrl = (p: string): string => `dramaclip://local/${encodeURIComponent(p)}`;
  function requestFor(p: string, range?: string): Request {
    return new Request(mediaUrl(p), range === undefined ? {} : { headers: { range } });
  }

  it('界内 Range 请求：206 + 定位读的字节与 content-range 头', async () => {
    const { base, inside } = makeFixture();
    const handler = createPreviewHandler(() => Promise.resolve([base]));
    const res = await handler(requestFor(inside, 'bytes=100-199'));
    expect(res.status).toBe(206);
    expect(res.headers.get('content-range')).toBe(`bytes 100-199/1000`);
    expect((await res.arrayBuffer()).byteLength).toBe(100);
  });

  it('界内无 Range：200 整读；起点越界：416', async () => {
    const { base, inside } = makeFixture();
    const handler = createPreviewHandler(() => Promise.resolve([base]));
    const full = await handler(requestFor(inside));
    expect(full.status).toBe(200);
    expect((await full.arrayBuffer()).byteLength).toBe(1000);
    const bad = await handler(requestFor(inside, 'bytes=5000-'));
    expect(bad.status).toBe(416);
  });

  it('围栏外路径与白名单外扩展名：403，不吐内容', async () => {
    const { base, outside, txt } = makeFixture();
    const handler = createPreviewHandler(() => Promise.resolve([base]));
    expect((await handler(requestFor(outside))).status).toBe(403);
    expect((await handler(requestFor(txt))).status).toBe(403);
  });

  it('围栏 miss 强刷后放行新素材根（TTL 未到也认新导入）', async () => {
    const { base, inside } = makeFixture();
    let roots: string[] = [];
    const handler = createPreviewHandler(() => Promise.resolve(roots));
    expect((await handler(requestFor(inside))).status).toBe(403);
    roots = [base];
    expect((await handler(requestFor(inside))).status).toBe(200);
  });

  it('不存在的文件：404', async () => {
    const handler = createPreviewHandler(() => Promise.resolve(['D:/whatever']));
    const res = await handler(requestFor('D:/no-such-dir/nope.mp4'));
    expect(res.status).toBe(404);
  });
});
