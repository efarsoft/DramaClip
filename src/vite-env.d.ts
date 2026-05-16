/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_APP_TITLE: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

// Electron API 类型声明（preload 暴露的接口）
interface ElectronBackendAPI {
  call<T = unknown>(method: string, params?: Record<string, unknown>): Promise<{
    success: boolean;
    data?: T;
    error?: { code: number; message: string; data?: unknown };
  }>;
  onProgress(callback: (payload: {
    task_id: string;
    progress: number;
    phase?: string;
    message: string;
    detail?: { current?: number; total?: number; episode_index?: number };
  }) => void): () => void;
  onLog(callback: (message: string, level: string) => void): () => void;
  onReady(callback: () => void): () => void;
  onError(callback: (error: string) => void): () => void;
}

interface ElectronDialogAPI {
  openFile(options?: Electron.OpenDialogOptions): Promise<{
    success: boolean;
    data?: string[];
    error?: { code: number; message: string };
  }>;
  openFolder(options?: Electron.OpenDialogOptions): Promise<{
    success: boolean;
    data?: string;
    error?: { code: number; message: string };
  }>;
  saveFile(options?: Electron.SaveDialogOptions): Promise<{
    success: boolean;
    data?: string;
    error?: { code: number; message: string };
  }>;
}

interface ElectronWindowAPI {
  minimize(): Promise<void>;
  maximize(): Promise<void>;
  close(): Promise<void>;
}

interface ElectronSystemAPI {
  getVersion(): Promise<{
    success: boolean;
    data?: { version: string };
    error?: { code: number; message: string };
  }>;
  getFFmpegInfo(): Promise<{
    success: boolean;
    data?: { available: boolean; version: string; hwaccel: string };
    error?: { code: number; message: string };
  }>;
  openPath(path: string): Promise<{
    success: boolean;
    data?: void;
    error?: { code: number; message: string };
  }>;
}

interface ElectronAPI {
  backend: ElectronBackendAPI;
  dialog: ElectronDialogAPI;
  window: ElectronWindowAPI;
  system: ElectronSystemAPI;
}

interface Window {
  electronAPI: ElectronAPI;
}
