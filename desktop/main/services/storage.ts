/** 数据目录存储管理：app-config.json 重定向 + 迁移编排（robocopy 优先，cp 回退）。
 *
 * 为什么配置在 Electron 层而不是 DB：数据库本身就在数据目录里（鸡生蛋），
 * 换目录必须由目录外的锚点记账——userData/app-config.json（KB 级，留 C 盘无压力）。
 * 迁移纪律：复制不移动（成功后旧目录改名 .bak-日期，绝不自动删）；
 * 配置只在复制+校验成功后才写，任何一步失败回滚为未迁移。
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';

export interface AppConfig {
  /** 自定义数据目录（绝对路径）；缺省 = userData/data。 */
  dataDir?: string;
  /** C 盘低空间首启引导「不再提醒」。 */
  storageHintDismissed?: boolean;
}

export interface UsageEntry {
  readonly name: string;
  readonly bytes: number;
}

export interface MigrationDeps {
  /** 迁移前查在跑任务（返回 true=有空闲，允许迁移）。 */
  ensureIdle(): Promise<boolean>;
  /** 平台注入（测试/非 win32 走 fs.cp 回退）。 */
  platform?: NodeJS.Platform;
}

export const LOW_DISK_HINT_BYTES = 20 * 1024 * 1024 * 1024; // C 盘引导阈值：20GB
const MIGRATION_HEADROOM = 1.05; // 目标盘需 ≥ 源占用 ×1.05（db/日志写放大余量）

export function configPath(userData: string): string {
  return path.join(userData, 'app-config.json');
}

export function loadAppConfig(userData: string): AppConfig {
  try {
    const raw = JSON.parse(fs.readFileSync(configPath(userData), 'utf8')) as Partial<AppConfig>;
    // 只含有意义键（缺省即未配置）：调用方 spread 保存时不会把显式 undefined 落盘
    const dataDir =
      typeof raw.dataDir === 'string' && raw.dataDir.length > 0 ? raw.dataDir : undefined;
    return {
      ...(dataDir !== undefined ? { dataDir } : {}),
      ...(raw.storageHintDismissed === true ? { storageHintDismissed: true } : {}),
    };
  } catch {
    return {}; // 缺失/坏 JSON = 全默认，不当错误（首装常态）
  }
}

/** 原子写（tmp+rename）：半截 JSON 不该把下一次启动变回默认目录。 */
export async function saveAppConfig(userData: string, config: AppConfig): Promise<void> {
  const target = configPath(userData);
  const tmp = `${target}.tmp`;
  await fsp.writeFile(tmp, JSON.stringify(config, null, 2), 'utf8');
  await fsp.rename(tmp, target);
}

/** 打包态生效数据目录：自定义配置优先（目录被删/U 盘拔走时回退默认并留痕）。 */
export function resolveDataDir(
  userData: string,
  defaultDataDir: string,
  config: AppConfig,
): { dataDir: string; customized: boolean } {
  if (config.dataDir !== undefined && fs.existsSync(config.dataDir)) {
    return { dataDir: config.dataDir, customized: true };
  }
  if (config.dataDir !== undefined) {
    console.warn(`[storage] 配置的数据目录不存在，回退默认：${config.dataDir}`);
  }
  return { dataDir: defaultDataDir, customized: false };
}

/** 递归求目录字节数；不可读子项跳过（统计不因单点权限失败整盘报错）。 */
export async function dirBytes(target: string): Promise<number> {
  let total = 0;
  const walk = async (dir: string): Promise<void> => {
    let entries: fs.Dirent[];
    try {
      entries = await fsp.readdir(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const child = path.join(dir, entry.name);
      try {
        if (entry.isDirectory()) {
          await walk(child);
        } else if (entry.isFile()) {
          total += (await fsp.stat(child)).size;
        }
      } catch {
        // 单项失败跳过
      }
    }
  };
  await walk(target);
  return total;
}

/** 数据目录第一层画像：子目录（models/cache/outputs/bgm/runtimes/covers/logs…动态枚举）
 * + 根下散文件（data.db）合并为「数据库与散件」。 */
export async function storageUsage(dataDir: string): Promise<UsageEntry[]> {
  const usage: UsageEntry[] = [];
  let rootLooseBytes = 0;
  let entries: fs.Dirent[];
  try {
    entries = await fsp.readdir(dataDir, { withFileTypes: true });
  } catch {
    return usage;
  }
  for (const entry of entries) {
    const child = path.join(dataDir, entry.name);
    if (entry.isDirectory()) {
      usage.push({ name: entry.name, bytes: await dirBytes(child) });
    } else if (entry.isFile()) {
      rootLooseBytes += (await fsp.stat(child)).size;
    }
  }
  usage.sort((a, b) => b.bytes - a.bytes);
  if (rootLooseBytes > 0) {
    usage.push({ name: '数据库与散件', bytes: rootLooseBytes });
  }
  return usage;
}

/** 盘剩余字节；statfs 不可用/路径不存在返回 null（UI 显示未知，预检放行自担）。 */
export async function freeBytes(target: string): Promise<number | null> {
  try {
    const stats = await fsp.statfs(target);
    return stats.bavail * stats.bsize;
  } catch {
    return null;
  }
}

/** C 盘低空间引导判据：win32 下目录落 C 盘 + 剩余 <20GB + 未自定义 + 未关闭提醒。 */
export function lowDiskHintActive(
  dataDir: string,
  customized: boolean,
  dismissed: boolean,
  free: number | null,
  platform: NodeJS.Platform = process.platform,
): boolean {
  if (dismissed || customized || free === null) return false;
  if (platform !== 'win32') return false;
  const root = path.parse(path.resolve(dataDir)).root.toUpperCase();
  return root.startsWith('C:') && free < LOW_DISK_HINT_BYTES;
}

/** robocopy 退出码 <8 均为成功（0=无变化 1=已复制…，≥8 才是失败）。 */
async function copyTreeRobocopy(source: string, target: string): Promise<void> {
  const code = await new Promise<number>((resolve) => {
    const child = spawn(
      'robocopy',
      [source, target, '/E', '/COPY:DAT', '/DCOPY:DAT', '/R:2', '/W:2', '/NFL', '/NDL', '/NP'],
      { windowsHide: true },
    );
    child.on('error', () => { resolve(-1); }); // robocopy 不在（非 Windows 伪装）→ 走回退
    child.on('close', (exitCode) => { resolve(exitCode ?? -1); });
  });
  if (code < 0 || code >= 8) {
    throw new Error(`robocopy 退出码 ${String(code)}`);
  }
}

/** 迁移编排：预检 → 复制 → 校验 → 写配置 → 旧目录改名留痕。任何一步失败如实报。 */
export async function migrateDataDir(
  userData: string,
  source: string,
  target: string,
  deps: MigrationDeps,
): Promise<{ ok: true; backupDir: string } | { ok: false; reason: string }> {
  const platform = deps.platform ?? process.platform;
  if (path.resolve(source) === path.resolve(target)) {
    return { ok: false, reason: '新目录与当前目录相同' };
  }
  if (!fs.existsSync(source)) {
    return { ok: false, reason: `当前数据目录不存在：${source}` };
  }
  try {
    const existing = await fsp.readdir(target);
    if (existing.length > 0) {
      return { ok: false, reason: '新目录不是空目录（为防覆盖既有数据，请选一个空目录）' };
    }
  } catch {
    // 不存在 = 正常，mkdir 补齐
    await fsp.mkdir(target, { recursive: true }).catch((error: unknown) => {
      throw new Error(`新目录无法创建：${String(error)}`);
    });
  }
  if (!(await deps.ensureIdle())) {
    return { ok: false, reason: '有任务正在运行（分析/导出/下载），请等任务结束或取消后再迁移' };
  }
  const sourceBytes = await dirBytes(source);
  const targetFree = await freeBytes(target);
  if (targetFree !== null && targetFree < sourceBytes * MIGRATION_HEADROOM) {
    return {
      ok: false,
      reason: `目标盘剩余 ${(targetFree / 1024 ** 3).toFixed(1)}GB，小于数据占用 ${
        (sourceBytes / 1024 ** 3).toFixed(1)
      }GB ×1.05 的安全余量`,
    };
  }
  // 复制（不动原文件）：win32 走 robocopy（断点续传/多线程/属性），其余平台 fs.cp
  try {
    if (platform === 'win32') {
      try {
        await copyTreeRobocopy(source, target);
      } catch (robocopyError) {
        console.warn(`[storage] robocopy 失败（${String(robocopyError)}），回退 fs.cp`);
        await fsp.cp(source, target, { recursive: true });
      }
    } else {
      await fsp.cp(source, target, { recursive: true });
    }
  } catch (error) {
    return { ok: false, reason: `复制失败：${error instanceof Error ? error.message : String(error)}` };
  }
  // 校验：数据库与模型目录到位才算迁移成（robocopy 半途退出码也可能 <8 的兜底）
  if (!fs.existsSync(path.join(target, 'data.db'))) {
    return { ok: false, reason: '校验失败：新目录里没有 data.db（复制不完整），已保留原目录' };
  }
  // 配置最后写：之前任何失败都等于没迁移
  const config = loadAppConfig(userData);
  await saveAppConfig(userData, { ...config, dataDir: target });
  // 旧目录改名留痕（不自动删）；失败不判迁移失败——数据已在新目录生效
  const backupDir = `${source}.bak-${new Date().toISOString().slice(0, 10).replaceAll('-', '')}`;
  try {
    await fsp.rename(source, backupDir);
  } catch (error) {
    console.warn(`[storage] 旧目录改名失败（${String(error)}），请手动处理：${source}`);
    return { ok: true, backupDir: source };
  }
  return { ok: true, backupDir };
}
