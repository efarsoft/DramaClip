/** ipcMain 通道唯一登记处（docs/desktop/00 §3）。 */
import { BrowserWindow, ipcMain } from 'electron';
import { METHOD_NAMES, type ServiceEvent } from '@dramaclip/protocol';
import { pickFolder, pickVideoFile } from './services/dialog';

export interface IpcContext {
  /** RPC 转发目标（ServiceManager.rpc）。 */
  rpc(method: string, params: Record<string, unknown>, timeoutMs?: number): Promise<unknown>;
  restartService(): void;
  appVersion(): string;
  /** 事件广播目标窗口集合（App 启动后传入 getter，避免持有过期引用）。 */
  windows(): BrowserWindow[];
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
  ipcMain.handle('dialog:pickFolder', (event) => pickFolder(BrowserWindow.fromWebContents(event.sender)));
  ipcMain.handle('dialog:pickVideoFile', (event) =>
    pickVideoFile(BrowserWindow.fromWebContents(event.sender)),
  );
  ipcMain.handle('service:restart', () => {
    context.restartService();
    return { ok: true };
  });
}

/** 主进程 → 渲染层事件下发（service:event）。 */
export function broadcastEvent(context: IpcContext, event: ServiceEvent): void {
  for (const win of context.windows()) {
    if (!win.isDestroyed()) win.webContents.send('service:event', event);
  }
}
