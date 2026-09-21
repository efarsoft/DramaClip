/** ipcMain 通道唯一登记处（docs/desktop/00 §3）。 */
import { BrowserWindow, ipcMain, shell } from 'electron';
import path from 'node:path';
import { METHOD_NAMES, type DataPaths, type ServiceEvent } from '@dramaclip/protocol';
import { pickAudioFile, pickFolder, pickVideoFile } from './services/dialog';

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
  };
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
  ipcMain.handle('shell:reveal', (_event, targetPath: unknown) => {
    if (typeof targetPath === 'string' && targetPath.length > 0) {
      shell.showItemInFolder(targetPath);
    }
    return { ok: true };
  });
  ipcMain.handle('service:restart', () => {
    context.restartService();
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
