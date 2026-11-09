/** ipcMain 通道唯一登记处（docs/desktop/00 §3）。 */
import { BrowserWindow, app, ipcMain, shell } from 'electron';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import {
  METHOD_NAMES,
  type CopyFilesResult,
  type DataPaths,
  type MigrationResult,
  type RevealResult,
  type ServiceEvent,
  type StorageInfo,
} from '@dramaclip/protocol';
import {
  freeBytes,
  loadAppConfig,
  lowDiskHintActive,
  migrateDataDir,
  saveAppConfig,
  storageUsage,
} from './services/storage';
import { pickAudioFile, pickFolder, pickVideoFile, saveTextFile } from './services/dialog';

export interface IpcContext {
  /** RPC 转发目标（ServiceManager.rpc）。 */
  rpc(method: string, params: Record<string, unknown>, timeoutMs?: number): Promise<unknown>;
  restartService(): void;
  appVersion(): string;
  /** 本地数据目录锚点（关于页「本地数据」）。 */
  dataPaths(): DataPaths;
  /** 事件广播目标窗口集合（App 启动后传入 getter，避免持有过期引用）。 */
  windows(): BrowserWindow[];
}

/** 数据目录 = 服务端 paths._SUBDIRS 的同名约定，锚点唯一（ADR-009）。 */
export function resolveDataPaths(dataDir: string): DataPaths {
  return {
    root: dataDir,
    outputs: path.join(dataDir, 'outputs'),
    models: path.join(dataDir, 'models'),
    logs: path.join(dataDir, 'logs'),
    trash: path.join(dataDir, '.trash'),
  };
}

/** 复制目标不覆盖同名文件：撞名加 -1、-2…后缀（回收站同款「不吞别人东西」规矩）。 */
function uniqueDest(destDir: string, fileName: string): string {
  const ext = path.extname(fileName);
  const base = path.basename(fileName, ext);
  let candidate = path.join(destDir, fileName);
  for (let index = 1; fs.existsSync(candidate); index += 1) {
    candidate = path.join(destDir, `${base}-${String(index)}${ext}`);
  }
  return candidate;
}

async function copyFiles(files: readonly string[], destDir: string): Promise<CopyFilesResult> {
  const copied: string[] = [];
  const failed: { path: string; reason: string }[] = [];
  await fsp.mkdir(destDir, { recursive: true });
  for (const file of files) {
    try {
      const dest = uniqueDest(destDir, path.basename(file));
      await fsp.copyFile(file, dest);
      copied.push(dest);
    } catch (error: unknown) {
      failed.push({ path: file, reason: error instanceof Error ? error.message : String(error) });
    }
  }
  return { copied, failed };
}

export function registerIpc(context: IpcContext): void {
  ipcMain.handle('rpc', (_event, method: unknown, params: unknown) => {
    if (typeof method !== 'string' || !(METHOD_NAMES as readonly string[]).includes(method)) {
      return Promise.reject(new Error(`未知 RPC 方法: ${String(method)}`));
    }
    const safeParams: Record<string, unknown> =
      typeof params === 'object' && params !== null ? (params as Record<string, unknown>) : {};
    return context.rpc(method, safeParams);
  });
  ipcMain.handle('app:version', () => context.appVersion());
  ipcMain.handle('app:paths', () => context.dataPaths());
  ipcMain.handle('dialog:pickFolder', (event) => pickFolder(BrowserWindow.fromWebContents(event.sender)));
  ipcMain.handle('dialog:pickVideoFile', (event) =>
    pickVideoFile(BrowserWindow.fromWebContents(event.sender)),
  );
  ipcMain.handle('dialog:pickAudioFile', (event) =>
    pickAudioFile(BrowserWindow.fromWebContents(event.sender)),
  );
  ipcMain.handle('dialog:saveTextFile', (_event, defaultName: unknown, content: unknown) => {
    if (typeof defaultName !== 'string' || defaultName.length === 0 || typeof content !== 'string') {
      return Promise.reject(new Error('saveTextFile 参数不合法'));
    }
    return saveTextFile(BrowserWindow.fromWebContents(_event.sender), defaultName, content);
  });
  ipcMain.handle('shell:reveal', (_event, targetPath: unknown): RevealResult => {
    if (typeof targetPath !== 'string' || targetPath.length === 0) {
      return { ok: false, reason: '路径为空' };
    }
    if (!fs.existsSync(targetPath)) {
      return { ok: false, reason: '路径不存在（可能已被移动或删除）' };
    }
    shell.showItemInFolder(targetPath);
    return { ok: true };
  });
  ipcMain.handle('shell:copyFiles', async (_event, files: unknown, destDir: unknown) => {
    if (
      !Array.isArray(files) ||
      files.some((item) => typeof item !== 'string' || item.length === 0) ||
      typeof destDir !== 'string' ||
      destDir.length === 0
    ) {
      return Promise.reject(new Error('copyFiles 参数不合法'));
    }
    return copyFiles(files as string[], destDir);
  });
  ipcMain.handle('service:restart', () => {
    context.restartService();
    return { ok: true };
  });
  ipcMain.handle('storage:info', async (): Promise<StorageInfo> => {
    const dataDir = context.dataPaths().root;
    const config = loadAppConfig(app.getPath('userData'));
    const defaultDataDir = path.join(app.getPath('userData'), 'data');
    const customized = config.dataDir !== undefined && config.dataDir === dataDir;
    const free = await freeBytes(dataDir);
    return {
      dataDir,
      defaultDataDir,
      customized,
      // 开发态数据目录由 DRAMACLIP_DATA_DIR 决定，配置重定向不参与：迁移不可用
      migrationAvailable: app.isPackaged,
      usage: await storageUsage(dataDir),
      freeBytes: free ?? 0,
      lowDiskHint: lowDiskHintActive(
        dataDir,
        customized,
        config.storageHintDismissed === true,
        free,
      ),
    };
  });
  ipcMain.handle('storage:migrate', async (_event, target: unknown): Promise<MigrationResult> => {
    if (typeof target !== 'string' || target.length === 0) {
      return { ok: false, reason: '目标目录参数不合法' };
    }
    const ensureIdle = async (): Promise<boolean> => {
      try {
        const result = (await context.rpc('jobs.list', {}, 10_000)) as {
          jobs?: { status?: string }[];
        };
        const active = (result.jobs ?? []).filter(
          (job) => job.status === 'pending' || job.status === 'running',
        );
        return active.length === 0;
      } catch {
        return false; // 服务无响应时不迁移（宁可拒绝不可带任务搬家）
      }
    };
    const migrated = await migrateDataDir(
      app.getPath('userData'),
      context.dataPaths().root,
      target,
      { ensureIdle },
    );
    return migrated.ok
      ? { ok: true, backupDir: migrated.backupDir }
      : { ok: false, reason: migrated.reason };
  });
  ipcMain.handle('storage:dismissHint', async () => {
    const config = loadAppConfig(app.getPath('userData'));
    await saveAppConfig(app.getPath('userData'), { ...config, storageHintDismissed: true });
  });
  ipcMain.handle('app:relaunch', () => {
    // 迁移成功后的归零动作：dataDir 锚点分散在 Electron 三处闭包，
    // 只重启 Python 服务不够——整应用重启让所有消费点重读 app-config。
    app.relaunch();
    app.exit(0);
    return { ok: true };
  });
  ipcMain.handle('window:control', (event, action: unknown) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    if (win === null || typeof action !== 'string') return { ok: false };
    if (action === 'minimize') win.minimize();
    else if (action === 'maximize-toggle') {
      if (win.isMaximized()) win.unmaximize();
      else win.maximize();
    } else if (action === 'close') win.close();
    return { ok: true };
  });
}

/** 主进程 → 渲染层事件下发（service:event）。 */
export function broadcastEvent(context: IpcContext, event: ServiceEvent): void {
  for (const win of context.windows()) {
    if (!win.isDestroyed()) win.webContents.send('service:event', event);
  }
}
