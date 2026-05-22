/**
 * 前端统一错误处理模块
 * P0 核心：提供用户友好的错误提示、错误分类、恢复建议
 */

import { message } from 'antd';

// ==================== 错误码定义 ====================

export const ErrorCode = {
  // 系统级错误 (-32000 ~ -32099)
  INTERNAL_ERROR: -32000,
  BACKEND_NOT_READY: -32001,
  FILE_NOT_FOUND: -32002,
  PERMISSION_DENIED: -32003,
  TIMEOUT: -32004,

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

export type ErrorCodeType = typeof ErrorCode[keyof typeof ErrorCode];

// ==================== 错误提示映射 ====================

interface ErrorHint {
  /** 简短标题 */
  short: string;
  /** 用户提示 */
  hint: string;
  /** 严重程度 */
  severity: 'error' | 'warning' | 'info';
  /** 是否可恢复 */
  recoverable: boolean;
}

const ERROR_HINTS: Record<number, ErrorHint> = {
  // 系统级错误
  [-32000]: {
    short: '操作失败',
    hint: '请稍后重试，如问题持续存在请联系技术支持',
    severity: 'error',
    recoverable: true,
  },
  [-32001]: {
    short: '服务未就绪',
    hint: '请重启应用',
    severity: 'error',
    recoverable: false,
  },
  [-32002]: {
    short: '文件未找到',
    hint: '请检查文件路径是否正确，或重新导入视频文件',
    severity: 'error',
    recoverable: true,
  },
  [-32003]: {
    short: '权限不足',
    hint: '请以管理员身份运行，或检查文件权限设置',
    severity: 'error',
    recoverable: false,
  },
  [-32004]: {
    short: '操作超时',
    hint: '请检查网络连接或减少操作规模后重试',
    severity: 'warning',
    recoverable: true,
  },

  // 项目错误
  [-32101]: {
    short: '项目不存在',
    hint: '请先创建项目或导入已有项目',
    severity: 'error',
    recoverable: true,
  },
  [-32102]: {
    short: '项目已存在',
    hint: '请使用现有项目或更改项目名称',
    severity: 'warning',
    recoverable: true,
  },

  // 分析错误
  [-32201]: {
    short: '语音识别失败',
    hint: '请检查音频文件是否完整，或尝试更换模型',
    severity: 'error',
    recoverable: true,
  },
  [-32202]: {
    short: '不支持的视频格式',
    hint: '支持的格式: MP4, AVI, MKV, MOV，请转换后重试',
    severity: 'error',
    recoverable: false,
  },

  // 剪辑错误
  [-32301]: {
    short: '高光片段不足',
    hint: '请调整高光检测参数或选择更多视频片段',
    severity: 'warning',
    recoverable: true,
  },
  [-32302]: {
    short: '语音合成失败',
    hint: '请检查网络连接或 API 配置',
    severity: 'error',
    recoverable: true,
  },

  // 导出错误
  [-32401]: {
    short: '视频导出失败',
    hint: '请检查磁盘空间是否充足，或尝试降低输出质量',
    severity: 'error',
    recoverable: true,
  },
  [-32402]: {
    short: '磁盘空间不足',
    hint: '请清理临时文件或释放磁盘空间',
    severity: 'error',
    recoverable: false,
  },

  // JSON-RPC 标准错误
  [-32600]: {
    short: '无效请求',
    hint: '请刷新页面后重试',
    severity: 'error',
    recoverable: true,
  },
  [-32601]: {
    short: '功能不可用',
    hint: '请联系技术支持',
    severity: 'error',
    recoverable: false,
  },
  [-32602]: {
    short: '参数错误',
    hint: '请检查输入参数是否正确',
    severity: 'error',
    recoverable: true,
  },
  [-32603]: {
    short: '服务端错误',
    hint: '请稍后重试',
    severity: 'error',
    recoverable: true,
  },
};

// ==================== IPC 异常类 ====================

export interface IpcError {
  code: number;
  message: string;
  data?: unknown;
}

export class AppException extends Error {
  code: number;
  data?: unknown;
  hint: ErrorHint;

  constructor(code: number, message: string, data?: unknown) {
    super(message);
    this.name = 'AppException';
    this.code = code;
    this.data = data;
    this.hint = ERROR_HINTS[code] || {
      short: '未知错误',
      hint: '请稍后重试',
      severity: 'error',
      recoverable: false,
    };
  }

  get shortMessage(): string {
    return this.hint.short;
  }

  get userHint(): string {
    return this.hint.hint;
  }

  get isRecoverable(): boolean {
    return this.hint.recoverable;
  }

  get severity(): 'error' | 'warning' | 'info' {
    return this.hint.severity;
  }

  toJSON() {
    return {
      code: this.code,
      message: this.message,
      short: this.shortMessage,
      hint: this.userHint,
      severity: this.severity,
      recoverable: this.isRecoverable,
      data: this.data,
    };
  }
}

// ==================== 错误处理工具函数 ====================

/**
 * 判断是否为 IPC 错误
 */
export function isIpcError(error: unknown): error is IpcError {
  if (typeof error !== 'object' || error === null) {
    return false;
  }
  const obj = error as Record<string, unknown>;
  return typeof obj.code === 'number' && typeof obj.message === 'string';
}

/**
 * 将原始错误转换为 AppException
 */
export function toAppException(error: unknown): AppException {
  if (error instanceof AppException) {
    return error;
  }

  if (error instanceof Error) {
    // 检查是否是 IPC 错误格式
    const ipcError = error as unknown as Record<string, unknown>;
    if (typeof ipcError.code === 'number') {
      return new AppException(
        ipcError.code,
        ipcError.message as string || error.message,
        ipcError.data
      );
    }

    // 根据错误类型推断
    if (error.name === 'AbortError' || error.message.includes('timeout')) {
      return new AppException(
        ErrorCode.TIMEOUT,
        '请求超时',
        { originalError: error.message }
      );
    }

    // 通用错误
    return new AppException(
      ErrorCode.INTERNAL_ERROR,
      error.message,
      { originalError: error.name }
    );
  }

  // 未知错误
  return new AppException(
    ErrorCode.INTERNAL_ERROR,
    String(error),
    { type: typeof error }
  );
}

/**
 * 获取错误提示
 */
export function getErrorHint(code: number): ErrorHint {
  return ERROR_HINTS[code] || {
    short: '未知错误',
    hint: '请稍后重试',
    severity: 'error',
    recoverable: false,
  };
}

/**
 * 显示错误消息
 */
export function showError(error: unknown, customMessage?: string): void {
  const appError = toAppException(error);
  const displayMessage = customMessage || appError.userHint;

  switch (appError.severity) {
    case 'error':
      message.error(displayMessage, 3);
      break;
    case 'warning':
      message.warning(displayMessage, 3);
      break;
    case 'info':
      message.info(displayMessage, 3);
      break;
  }

  // 开发模式下同时打印详细信息
  if (import.meta.env.DEV) {
    console.error('[AppException]', appError.toJSON());
  }
}

/**
 * 显示成功消息
 */
export function showSuccess(messageText: string): void {
  message.success(messageText, 2);
}

/**
 * 显示警告消息
 */
export function showWarning(messageText: string): void {
  message.warning(messageText, 3);
}

/**
 * 显示信息消息
 */
export function showInfo(messageText: string): void {
  message.info(messageText, 2);
}

// ==================== 错误边界组件 ====================

export interface ErrorBoundaryState {
  hasError: boolean;
  error: AppException | null;
}

/**
 * 创建错误边界状态
 */
export function createErrorBoundaryState(): ErrorBoundaryState {
  return {
    hasError: false,
    error: null,
  };
}

/**
 * 记录错误到日志（可用于日志服务集成）
 */
export function logError(error: AppException, context?: Record<string, unknown>): void {
  const logData = {
    ...error.toJSON(),
    context,
    timestamp: new Date().toISOString(),
    userAgent: navigator.userAgent,
    url: window.location.href,
  };

  // 生产环境发送到日志服务
  if (import.meta.env.PROD) {
    // TODO: 集成日志服务
    console.error('[Error Log]', logData);
  } else {
    console.error('[Error Log]', logData);
  }
}
