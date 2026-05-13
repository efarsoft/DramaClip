/**
 * IPC 通信相关类型定义
 */

export interface IpcRequest<T = unknown> {
  success: boolean;
  data?: T;
  error?: IpcError;
}

export interface IpcError {
  code: number;
  message: string;
  data?: unknown;
}

export interface ProgressPayload {
  task_id: string;
  progress: number;
  phase?: string;
  message: string;
  detail?: ProgressDetail;
}

export interface ProgressDetail {
  current?: number;
  total?: number;
  episode_index?: number;
  [key: string]: unknown;
}

export interface LogPayload {
  message: string;
  level: 'debug' | 'info' | 'warning' | 'error';
  timestamp?: string;
}

// 错误码定义
export const IPC_ERROR_CODES = {
  // 系统级错误 (-32000 ~ -32099)
  INTERNAL_ERROR: -32000,
  BACKEND_NOT_READY: -32001,
  FILE_NOT_FOUND: -32002,
  PERMISSION_DENIED: -32003,

  // 项目错误 (-32100 ~ -32199)
  PROJECT_NOT_FOUND: -32101,
  PROJECT_ALREADY_EXISTS: -32102,

  // 分析错误 (-32200 ~ -32299)
  ASR_FAILED: -32201,
  UNSUPPORTED_VIDEO_FORMAT: -32202,

  // 剪辑错误 (-32300 ~ -32399)
  INSUFFICIENT_HIGHLIGHTS: -32301,
  TTS_SYNTHESIS_FAILED: -32302,

  // 导出错误 (-32400 ~ -32499)
  FFMPEG_EXECUTION_FAILED: -32401,
  INSUFFICIENT_DISK_SPACE: -32402,

  // JSON-RPC 标准错误
  INVALID_REQUEST: -32600,
  METHOD_NOT_FOUND: -32601,
  INVALID_PARAMS: -32602,
  INTERNAL_RPC_ERROR: -32603,
} as const;
