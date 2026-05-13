/**
 * Preload 脚本
 * 在渲染进程和主进程之间建立安全的桥接
 */

import { contextBridge, ipcRenderer, IpcRendererEvent } from 'electron';

// IPC 通道名常量
export const IPC_CHANNELS = {
  // 对话框
  DIALOG_OPEN_FILE: 'dialog:openFile',
  DIALOG_OPEN_FOLDER: 'dialog:openFolder',
  DIALOG_SAVE_FILE: 'dialog:saveFile',

  // 后端调用
  BACKEND_CALL: 'backend:call',
  BACKEND_PROGRESS: 'backend:progress',
  BACKEND_LOG: 'backend:log',
  BACKEND_READY: 'backend:ready',
  BACKEND_ERROR: 'backend:error',

  // 窗口控制
  WINDOW_MINIMIZE: 'window:minimize',
  WINDOW_MAXIMIZE: 'window:maximize',
  WINDOW_CLOSE: 'window:close',

  // 系统
  SYSTEM_GET_VERSION: 'system:getVersion',
  SYSTEM_GET_FFMPEG_INFO: 'system:getFFmpegInfo',
  SYSTEM_OPEN_PATH: 'system:openPath',
} as const;

// 类型定义
export interface IpcResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: {
    code: number;
    message: string;
    data?: unknown;
  };
}

export interface ProgressPayload {
  task_id: string;
  progress: number;
  phase?: string;
  message: string;
  detail?: {
    current?: number;
    total?: number;
    episode_index?: number;
  };
}

// 暴露给渲染进程的 API
const electronAPI = {
  // 对话框
  dialog: {
    openFile: (options?: Electron.OpenDialogOptions): Promise<IpcResponse<string[]>> =>
      ipcRenderer.invoke(IPC_CHANNELS.DIALOG_OPEN_FILE, options),
    openFolder: (options?: Electron.OpenDialogOptions): Promise<IpcResponse<string>> =>
      ipcRenderer.invoke(IPC_CHANNELS.DIALOG_OPEN_FOLDER, options),
    saveFile: (options?: Electron.SaveDialogOptions): Promise<IpcResponse<string>> =>
      ipcRenderer.invoke(IPC_CHANNELS.DIALOG_SAVE_FILE, options),
  },

  // 后端调用
  backend: {
    call: <T = unknown>(method: string, params?: Record<string, unknown>): Promise<IpcResponse<T>> =>
      ipcRenderer.invoke(IPC_CHANNELS.BACKEND_CALL, method, params),
    onProgress: (callback: (payload: ProgressPayload) => void): (() => void) => {
      const handler = (_event: IpcRendererEvent, payload: ProgressPayload) => callback(payload);
      ipcRenderer.on(IPC_CHANNELS.BACKEND_PROGRESS, handler);
      return () => ipcRenderer.removeListener(IPC_CHANNELS.BACKEND_PROGRESS, handler);
    },
    onLog: (callback: (message: string, level: string) => void): (() => void) => {
      const handler = (_event: IpcRendererEvent, message: string, level: string) => callback(message, level);
      ipcRenderer.on(IPC_CHANNELS.BACKEND_LOG, handler);
      return () => ipcRenderer.removeListener(IPC_CHANNELS.BACKEND_LOG, handler);
    },
    onReady: (callback: () => void): (() => void) => {
      const handler = () => callback();
      ipcRenderer.on(IPC_CHANNELS.BACKEND_READY, handler);
      return () => ipcRenderer.removeListener(IPC_CHANNELS.BACKEND_READY, handler);
    },
    onError: (callback: (error: string) => void): (() => void) => {
      const handler = (_event: IpcRendererEvent, error: string) => callback(error);
      ipcRenderer.on(IPC_CHANNELS.BACKEND_ERROR, handler);
      return () => ipcRenderer.removeListener(IPC_CHANNELS.BACKEND_ERROR, handler);
    },
  },

  // 窗口控制
  window: {
    minimize: (): Promise<void> => ipcRenderer.invoke(IPC_CHANNELS.WINDOW_MINIMIZE),
    maximize: (): Promise<void> => ipcRenderer.invoke(IPC_CHANNELS.WINDOW_MAXIMIZE),
    close: (): Promise<void> => ipcRenderer.invoke(IPC_CHANNELS.WINDOW_CLOSE),
  },

  // 系统
  system: {
    getVersion: (): Promise<IpcResponse<{ version: string }>> =>
      ipcRenderer.invoke(IPC_CHANNELS.SYSTEM_GET_VERSION),
    getFFmpegInfo: (): Promise<IpcResponse<{ available: boolean; version: string; hwaccel: string }>> =>
      ipcRenderer.invoke(IPC_CHANNELS.SYSTEM_GET_FFMPEG_INFO),
    openPath: (path: string): Promise<IpcResponse<void>> =>
      ipcRenderer.invoke(IPC_CHANNELS.SYSTEM_OPEN_PATH, path),
  },
};

// 暴露 API 到渲染进程
contextBridge.exposeInMainWorld('electronAPI', electronAPI);

// TypeScript 类型声明
export type ElectronAPI = typeof electronAPI;
