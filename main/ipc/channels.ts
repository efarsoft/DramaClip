/**
 * IPC 通道常量定义
 */

export const IPC_CHANNELS = {
  // ============= 对话框 =============
  DIALOG_OPEN_FILE: 'dialog:openFile',
  DIALOG_OPEN_FOLDER: 'dialog:openFolder',
  DIALOG_SAVE_FILE: 'dialog:saveFile',

  // ============= 后端调用 =============
  BACKEND_CALL: 'backend:call',
  BACKEND_PROGRESS: 'backend:progress',
  BACKEND_LOG: 'backend:log',
  BACKEND_READY: 'backend:ready',
  BACKEND_ERROR: 'backend:error',

  // ============= 窗口控制 =============
  WINDOW_MINIMIZE: 'window:minimize',
  WINDOW_MAXIMIZE: 'window:maximize',
  WINDOW_CLOSE: 'window:close',

  // ============= 系统 =============
  SYSTEM_GET_VERSION: 'system:getVersion',
  SYSTEM_GET_FFMPEG_INFO: 'system:getFFmpegInfo',
  SYSTEM_OPEN_PATH: 'system:openPath',

  // ============= 文件系统 =============
  FS_SCAN_DIRECTORY: 'fs:scanDirectory',
} as const;

export type IpcChannel = typeof IPC_CHANNELS[keyof typeof IPC_CHANNELS];
