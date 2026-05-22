/**
 * 后端进程管理器
 * 负责 backend.exe 的生命周期管理、进程通信
 */

import { spawn, ChildProcess } from 'child_process';
import { EventEmitter } from 'events';
import { app } from 'electron';
import { JSONRPCProtocol } from './protocol';

export interface BackendOptions {
  backendPath: string;
  cwd?: string;
  env?: NodeJS.ProcessEnv;
}

export interface RpcRequest {
  jsonrpc: '2.0';
  method: string;
  params?: Record<string, unknown>;
  id: number;
}

export interface RpcResponse {
  jsonrpc: '2.0';
  result?: unknown;
  error?: {
    code: number;
    message: string;
    data?: unknown;
  };
  id: number;
}

export interface ProgressNotification {
  task_id: string;
  progress: number;
  phase?: string;
  message: string;
  detail?: Record<string, unknown>;
}

const HEARTBEAT_INTERVAL = 5000; // 5 秒
const MAX_RESTART_ATTEMPTS = 3;
const RESTART_DELAY = 2000; // 2 秒

export class BackendManager extends EventEmitter {
  private backendPath: string;
  private cwd?: string;
  private env?: NodeJS.ProcessEnv;
  private process: ChildProcess | null = null;
  private protocol: JSONRPCProtocol;
  private requestId = 0;
  private pendingRequests = new Map<number, { resolve: (value: unknown) => void; reject: (error: Error) => void }>();
  private isRunning = false;
  private isShuttingDown = false;

  // 心跳和重启
  private heartbeatInterval: NodeJS.Timeout | null = null;
  private lastPongTime = 0;
  private restartAttempts = 0;
  private pongTimeout: NodeJS.Timeout | null = null;

  private cleanup(): void {
    this.isRunning = false;
    this.isShuttingDown = true;

    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
    if (this.pongTimeout) {
      clearTimeout(this.pongTimeout);
      this.pongTimeout = null;
    }

    // 取消所有待处理的请求
    for (const [id, pending] of this.pendingRequests) {
      pending.reject(new Error('Backend disconnected'));
      this.pendingRequests.delete(id);
    }

    this.process = null;
  }

  async call<T = unknown>(method: string, params?: Record<string, unknown>): Promise<T> {
    if (!this.isRunning || !this.process?.stdin) {
      throw new Error('Backend not running');
    }

    const id = ++this.requestId;
    const request: RpcRequest = {
      jsonrpc: '2.0',
      method,
      params,
      id,
    };

    console.log(`[Main][BackendManager] Request sent: method=${method}, id=${id}`, JSON.stringify(params));

    return new Promise((resolve, reject) => {
      this.pendingRequests.set(id, { resolve: resolve as (value: unknown) => void, reject });

      try {
        const requestStr = JSON.stringify(request) + '\n';
        this.process!.stdin!.write(requestStr, (error) => {
          if (error) {
            console.error(`[Main][BackendManager] Write failed: method=${method}, id=${id}`, error);
            this.pendingRequests.delete(id);
            reject(error);
          }
        });
      } catch (error) {
        console.error(`[Main][BackendManager] Write exception: method=${method}, id=${id}`, error);
        this.pendingRequests.delete(id);
        reject(error);
      }

      // 超时处理（默认 60 秒，长任务可调整）
      const timeout = (params as Record<string, unknown>)?.timeout as number || 60000;
      setTimeout(() => {
        if (this.pendingRequests.has(id)) {
          this.pendingRequests.delete(id);
          console.warn(`[Main][BackendManager] Request timed out: method=${method}, id=${id}, timeout=${timeout}ms`);
          reject(new Error(`Request ${method} timed out after ${timeout}ms`));
        }
      }, timeout);
    });
  }

  constructor(backendPath: string, cwd?: string, env?: NodeJS.ProcessEnv) {
    super();
    this.backendPath = backendPath;
    this.cwd = cwd;
    this.env = env;
    this.protocol = new JSONRPCProtocol();
  }

  async start(): Promise<void> {
    if (this.isRunning) {
      console.log('[Main][BackendManager] Backend already running');
      return;
    }

    this.isShuttingDown = false;

    return new Promise((resolve, reject) => {
      console.log('[Main][BackendManager] Starting backend:', this.backendPath);

      try {
        // 处理 Python 脚本
        const isPythonScript = this.backendPath.endsWith('.py');
        let command: string;
        const args: string[] = [];

        if (isPythonScript) {
          const path = require('path');
          const fs = require('fs');

          // 根据系统平台确定 Python 可执行文件名及虚拟环境的子目录结构
          const isWin = process.platform === 'win32';
          const pythonExeName = isWin ? 'python.exe' : 'python';
          const venvSubPath = isWin ? ['Scripts', 'python.exe'] : ['bin', 'python'];

          // 候选 Python 解释器路径列表（优先级从高到低）
          const pythonCandidates: string[] = [];

          if (app.isPackaged) {
            // 生产环境下：优先查找打包内置的 Python 解释器或内置虚拟环境
            pythonCandidates.push(
              path.join(process.resourcesPath, 'python', pythonExeName),
              path.join(process.resourcesPath, 'backend', 'python', pythonExeName),
              path.join(process.resourcesPath, '.venv', ...venvSubPath),
              path.join(process.resourcesPath, 'backend', '.venv', ...venvSubPath)
            );
          } else {
            // 开发环境下：优先使用项目根目录下的 .venv 虚拟环境
            pythonCandidates.push(
              path.join(process.cwd(), '.venv', ...venvSubPath)
            );
          }

          // 寻找第一个存在的解释器
          let foundPython = '';
          for (const cand of pythonCandidates) {
            if (fs.existsSync(cand)) {
              foundPython = cand;
              break;
            }
          }

          if (foundPython) {
            command = foundPython;
            console.log('[Main][BackendManager] Using built-in/venv Python interpreter:', foundPython);
          } else {
            command = isWin ? 'python' : 'python3';
            console.warn('[Main][BackendManager] Built-in Python interpreter or .venv not found, falling back to system Python:', command);
          }
          args.push(this.backendPath);
        } else {
          command = this.backendPath;
        }

        this.process = spawn(command, args, {
          stdio: ['pipe', 'pipe', 'pipe'],
          cwd: this.cwd,
          env: { ...process.env, PYTHONUNBUFFERED: '1', ...this.env },
          windowsHide: true,
        });
      } catch (error) {
        reject(error);
        return;
      }

      const { stdin, stdout, stderr } = this.process;

      if (!stdin || !stdout || !stderr) {
        reject(new Error('Failed to create stdio streams'));
        return;
      }

      // 使用递归读取器处理不完整的行（移除上面重复的原始数据监听器）
      let buffer = '';
      stdout.on('data', (data: Buffer) => {
        buffer += data.toString();
        const lines = buffer.split('\n');
        buffer = lines.pop() || ''; // 保留不完整的最后一行

        for (const line of lines) {
          const trimmed = line.trim();
          if (trimmed) {
            this.handleStdoutData(trimmed);
          }
        }
      });

      // 处理 stderr（日志）
      stderr.on('data', (data: Buffer) => {
        const message = data.toString().trim();
        if (message) {
          console.log('[Backend]', message);
          this.emit('log', message, 'info');
        }
      });

      // 进程退出
      this.process.on('exit', (code, signal) => {
        console.log(`[Main][BackendManager] Backend exited, code: ${code}, signal: ${signal}`);
        this.cleanup();
        this.emit('exit', code, signal);

        // 非正常退出时尝试重启
        if (!this.isShuttingDown && code !== 0 && this.restartAttempts < MAX_RESTART_ATTEMPTS) {
          this.attemptRestart();
        }
      });

      // 进程错误
      this.process.on('error', (error) => {
        console.error('[Main][BackendManager] Backend error:', error);
        this.emit('error', error);
        reject(error);
      });

      this.isRunning = true;
      this.lastPongTime = Date.now();
      this.startHeartbeat();
      this.emit('ready');
      console.log('[Main][BackendManager] Backend started successfully');
      resolve();
    });
  }

  private handleStdoutData(data: string): void {
    try {
      const parsed = JSON.parse(data);

      // pong 响应（支持两种格式）
      if (parsed.method === 'pong' || (parsed.id === -1 && parsed.result?.pong)) {
        this.lastPongTime = Date.now();
        this.emit('pong');
        return;
      }

      // 进度通知（无 id）
      if (parsed.method && parsed.params && parsed.method !== 'log.append') {
        this.emit('progress', parsed.params as ProgressNotification);
        return;
      }

      // 日志通知
      if (parsed.method === 'log.append' && parsed.params) {
        this.emit('log', parsed.params.message, parsed.params.level || 'info');
        return;
      }

      // 就绪通知
      if (parsed.method === 'ready' && parsed.params) {
        this.emit('backendReady', parsed.params);
        return;
      }

      // RPC 响应（有 id）
      if (parsed.id !== undefined && parsed.id !== null) {
        const id = typeof parsed.id === 'number' ? parsed.id : parseInt(String(parsed.id), 10);
        const pending = this.pendingRequests.get(id);
        if (pending) {
          this.pendingRequests.delete(id);
          if (parsed.error) {
            pending.reject(new Error(parsed.error.message));
          } else {
            pending.resolve(parsed.result);
          }
        }
      }
    } catch (error) {
      // 忽略无法解析的数据
    }
  }

  private startHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
    }

    this.heartbeatInterval = setInterval(() => {
      if (!this.isRunning || !this.process?.stdin) {
        return;
      }

      // 检查是否超时
      const timeSincePong = Date.now() - this.lastPongTime;
      if (timeSincePong > HEARTBEAT_INTERVAL * 3) {
        console.warn('[Main][BackendManager] Heartbeat timeout, backend may be unresponsive');
        this.emit('heartbeatTimeout');
      }

      // 发送 ping
      try {
        const pingRequest = JSON.stringify({
          jsonrpc: '2.0',
          method: 'system.ping',
          params: { timestamp: Date.now() },
          id: -1, // 特殊 id 用于心跳
        });
        this.process.stdin.write(pingRequest + '\n');
      } catch (error) {
        console.error('[Main][BackendManager] Failed to send ping:', error);
      }
    }, HEARTBEAT_INTERVAL);
  }

  private async attemptRestart(): Promise<void> {
    this.restartAttempts++;
    console.log(`[Main][BackendManager] Attempting restart ${this.restartAttempts}/${MAX_RESTART_ATTEMPTS}`);

    // 清理待处理的请求
    for (const [, pending] of this.pendingRequests) {
      pending.reject(new Error('Backend restarted'));
    }
    this.pendingRequests.clear();

    // 延迟重启
    setTimeout(async () => {
      try {
        await this.start();
        this.restartAttempts = 0;
        this.emit('restarted');
      } catch (error) {
        console.error('[Main][BackendManager] Restart failed:', error);
        if (this.restartAttempts < MAX_RESTART_ATTEMPTS) {
          this.attemptRestart();
        } else {
          this.emit('maxRestartAttemptsReached');
        }
      }
    }, this.restartAttempts * 2000);
  }

  async stop(): Promise<void> {
    this.isShuttingDown = true;

    return new Promise((resolve) => {
      console.log('[Main][BackendManager] Stopping backend...');

      this.cleanup();

      // 发送优雅退出信号
      try {
        const shutdownRequest = JSON.stringify({
          jsonrpc: '2.0',
          method: 'shutdown',
          params: { reason: 'main_process_shutdown' },
          id: -1,
        });
        this.process?.stdin?.write(shutdownRequest + '\n');
      } catch (error) {
        console.error('[Main][BackendManager] Failed to send shutdown signal:', error);
      }

      // 等待退出
      const timeout = setTimeout(() => {
        if (this.process) {
          console.log('[Main][BackendManager] Force killing backend...');
          this.process.kill('SIGTERM');
        }
        resolve();
      }, 3000);
      this.process?.once('exit', () => {
        clearTimeout(timeout);
        this.process = null;
        resolve();
      });
    });
  }

  isBackendRunning(): boolean {
    return this.isRunning;
  }

  getPid(): number | null {
    return this.process?.pid || null;
  }

  getRestartAttempts(): number {
    return this.restartAttempts;
  }
}
