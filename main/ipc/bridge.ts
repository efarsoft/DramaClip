/**
 * IPC 桥接层
 * 注册所有 IPC 处理器，转发前端请求到 backend.exe
 */

import { ipcMain, BrowserWindow, dialog, app } from 'electron';
import { IPC_CHANNELS } from './channels';
import { BackendManager } from '../backend/manager';
import { DialogService } from '../services/dialog';
import { WindowManager } from '../window/manager';

// 获取后端管理器实例（从 app.ts 导入）
let backendManager: BackendManager | null = null;
let windowManager: WindowManager | null = null;

export function setBackendManager(manager: BackendManager): void {
  backendManager = manager;
}

export function setWindowManager(manager: WindowManager): void {
  windowManager = manager;
}

function getMainWindow(): BrowserWindow | null {
  return BrowserWindow.getAllWindows()[0] || null;
}

function forwardProgress(payload: unknown): void {
  const mainWindow = getMainWindow();
  if (mainWindow) {
    mainWindow.webContents.send(IPC_CHANNELS.BACKEND_PROGRESS, payload);
  }
}

function forwardLog(message: string, level: string): void {
  const mainWindow = getMainWindow();
  if (mainWindow) {
    mainWindow.webContents.send(IPC_CHANNELS.BACKEND_LOG, message, level);
  }
}

export function setupIpcHandlers(): void {
  // ============= 对话框处理器 =============
  ipcMain.handle(IPC_CHANNELS.DIALOG_OPEN_FILE, async (_event, options) => {
    return DialogService.openFile(options);
  });

  ipcMain.handle(IPC_CHANNELS.DIALOG_OPEN_FOLDER, async (_event, options) => {
    return DialogService.openFolder(options);
  });

  ipcMain.handle(IPC_CHANNELS.DIALOG_SAVE_FILE, async (_event, options) => {
    return DialogService.saveFile(options);
  });

  // ============= 后端调用处理器 =============
  ipcMain.handle(IPC_CHANNELS.BACKEND_CALL, async (_event, method: string, params?: Record<string, unknown>) => {
    if (!backendManager) {
      return {
        success: false,
        error: { code: -32001, message: 'Backend not initialized', data: null },
      };
    }

    try {
      const result = await backendManager.call(method, params);
      return { success: true, data: result };
    } catch (error) {
      return {
        success: false,
        error: {
          code: -32001,
          message: error instanceof Error ? error.message : 'Unknown error',
          data: error,
        },
      };
    }
  });

  // ============= 窗口控制处理器 =============
  ipcMain.handle(IPC_CHANNELS.WINDOW_MINIMIZE, () => {
    const mainWindow = getMainWindow();
    if (mainWindow) {
      mainWindow.minimize();
    }
  });

  ipcMain.handle(IPC_CHANNELS.WINDOW_MAXIMIZE, () => {
    const mainWindow = getMainWindow();
    if (mainWindow) {
      if (mainWindow.isMaximized()) {
        mainWindow.unmaximize();
      } else {
        mainWindow.maximize();
      }
    }
  });

  ipcMain.handle(IPC_CHANNELS.WINDOW_CLOSE, () => {
    const mainWindow = getMainWindow();
    if (mainWindow) {
      mainWindow.close();
    }
  });

  // ============= 系统处理器 =============
  ipcMain.handle(IPC_CHANNELS.SYSTEM_GET_VERSION, () => {
    return {
      success: true,
      data: {
        version: app.getVersion(),
        name: app.getName(),
      },
    };
  });

  ipcMain.handle(IPC_CHANNELS.SYSTEM_GET_FFMPEG_INFO, async () => {
    if (!backendManager) {
      return {
        success: false,
        error: { code: -32001, message: 'Backend not initialized', data: null },
      };
    }

    try {
      const result = await backendManager.call('system.getFFmpegInfo', {});
      return { success: true, data: result };
    } catch (error) {
      return {
        success: false,
        error: {
          code: -32001,
          message: error instanceof Error ? error.message : 'Failed to get FFmpeg info',
          data: error,
        },
      };
    }
  });

  console.log('[Main][IpcBridge] IPC handlers registered');
}
