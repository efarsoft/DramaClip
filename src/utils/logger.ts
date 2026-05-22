/**
 * 统一日志工具模块
 * 提供结构化的日志记录功能
 */

import dayjs from 'dayjs';

export enum LogLevel {
  DEBUG = 'DEBUG',
  INFO = 'INFO',
  WARNING = 'WARNING',
  ERROR = 'ERROR',
}

interface LogEntry {
  timestamp: string;
  level: LogLevel;
  module: string;
  message: string;
  data?: any;
}

class Logger {
  private module: string;
  private enableConsole: boolean = true;

  constructor(module: string) {
    this.module = module;
  }

  private formatMessage(level: LogLevel, message: string, data?: any): string {
    const timestamp = dayjs().format('YYYY-MM-DD HH:mm:ss.SSS');
    const dataStr = data ? ` | ${JSON.stringify(data)}` : '';
    return `[${timestamp}] [${level}] [${this.module}] ${message}${dataStr}`;
  }

  private log(level: LogLevel, message: string, data?: any): void {
    if (!this.enableConsole) return;

    const formatted = this.formatMessage(level, message, data);

    switch (level) {
      case LogLevel.DEBUG:
        console.debug(formatted);
        break;
      case LogLevel.INFO:
        console.info(formatted);
        break;
      case LogLevel.WARNING:
        console.warn(formatted);
        break;
      case LogLevel.ERROR:
        console.error(formatted);
        break;
    }
  }

  debug(message: string, data?: any): void {
    this.log(LogLevel.DEBUG, message, data);
  }

  info(message: string, data?: any): void {
    this.log(LogLevel.INFO, message, data);
  }

  warn(message: string, data?: any): void {
    this.log(LogLevel.WARNING, message, data);
  }

  error(message: string, data?: any): void {
    this.log(LogLevel.ERROR, message, data);
  }

  setEnableConsole(enable: boolean): void {
    this.enableConsole = enable;
  }
}

export function createLogger(module: string): Logger {
  return new Logger(module);
}

// 常用模块日志实例
export const logger = {
  app: createLogger('App'),
  ipc: createLogger('IPC'),
  project: createLogger('Project'),
  analysis: createLogger('Analysis'),
  clip: createLogger('Clip'),
  export: createLogger('Export'),
  ui: createLogger('UI'),
  store: createLogger('Store'),
};

export default Logger;
