/**
 * Python 服务进程全生命周期管理（docs/desktop/00 §6）：
 * spawn → hello 握手 → 心跳 → 崩溃退避重启 → 优雅退出。
 */
import { spawn, type ChildProcess } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { existsSync } from 'node:fs';
import path from 'node:path';
import type { NotificationName, ServiceEvent, ServiceState } from '@dramaclip/protocol';
import { createPipeServer, type PipeServer } from './pipe-server';
import { RestartPolicy } from './restart-policy';

const HEARTBEAT_INTERVAL_MS = 5_000;
const HEARTBEAT_TIMEOUT_MS = 4_000;
const HEARTBEAT_MAX_FAILURES = 3;
const SHUTDOWN_GRACE_MS = 3_000;

export interface ServiceManagerOptions {
  readonly repoRoot: string;
  /** 随应用分发的只读资源根（ffmpeg/sidecar），经环境变量注入 Python 服务。 */
  readonly resourcesDir: string;
  /** 服务进程工作目录。 */
  readonly cwd: string;
  readonly dataDir: string;
  readonly appVersion: string;
  readonly isPackaged: boolean;
  /** 测试注入：spawn 目标（缺省按 isPackaged 解析 venv/sidecar）。 */
  readonly pythonTarget?: PythonTarget;
  /** 测试注入：重启策略（缺省 3 次退避 2/4/6s、稳定 60s 清零）。 */
  readonly policy?: RestartPolicy;
  readonly onStateChange: (state: ServiceState) => void;
  readonly onEvent: (event: ServiceEvent) => void;
}

interface PythonTarget {
  readonly command: string;
  readonly args: readonly string[];
}

export function resolvePythonTarget(options: ServiceManagerOptions): PythonTarget {
  if (options.isPackaged) {
    // PyInstaller onedir sidecar（scripts/build-service.py 产物）
    return {
      command: path.join(options.resourcesDir, 'dramaclip-service', 'dramaclip-service.exe'),
      args: [],
    };
  }
  const venvPython = path.join(
    options.repoRoot,
    '.venv',
    process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
  );
  return { command: existsSync(venvPython) ? venvPython : 'python', args: ['-m', 'dramaclip'] };
}

export class ServiceManager {
  private readonly options: ServiceManagerOptions;
  private readonly policy: RestartPolicy;
  private pipeServer: PipeServer | null = null;
  private child: ChildProcess | null = null;
  private heartbeatTimer: NodeJS.Timeout | null = null;
  private heartbeatFailures = 0;
  private restartTimer: NodeJS.Timeout | null = null;
  private token = '';
  private state: ServiceState = 'starting';
  private stopping = false;
  private manualRespawn = false;

  constructor(options: ServiceManagerOptions) {
    this.options = options;
    this.policy = options.policy ?? new RestartPolicy();
  }

  get currentState(): ServiceState {
    return this.state;
  }

  async start(): Promise<void> {
    this.stopping = false;
    this.token = randomBytes(32).toString('hex');
    this.pipeServer = createPipeServer({
      token: this.token,
      appVersion: this.options.appVersion,
      onClientReady: () => {
        this.handleReady();
      },
      onClientDisconnect: () => {
        if (!this.stopping) this.fail('连接断开');
      },
      onNotification: (method, params) => {
        this.options.onEvent({
          type: 'notification',
          // 受信对端（认证后的 Python 服务），方法名值域由 protocol 契约保证
          method: method as NotificationName,
          params,
        });
      },
    });
    await this.pipeServer.listening;
    this.spawnProcess();
  }

  rpc(method: string, params: Record<string, unknown>, timeoutMs?: number): Promise<unknown> {
    if (this.pipeServer === null) return Promise.reject(new Error('服务未启动'));
    return this.pipeServer.call(method, params, timeoutMs);
  }

  restart(): void {
    // 手动重启是用户动作：不进崩溃账本、不等退避。give-up 后 child 已收走、
    // 不会再有 exit 事件来接力——这里直接重拉，保证按钮在任何状态下都有效。
    this.clearTimers();
    this.stopHeartbeat();
    this.policy.reset();
    const child = this.child;
    if (child !== null && child.exitCode === null) {
      this.manualRespawn = true; // killChild 的 exit 回调据此立即重拉，不走 fail 退避
      this.killChild();
    } else {
      this.spawnProcess();
    }
  }

  async stop(): Promise<void> {
    this.stopping = true;
    this.clearTimers();
    try {
      await this.rpc('system.shutdown', {}, SHUTDOWN_GRACE_MS - 500);
    } catch {
      // 服务无响应时直接走强杀
    }
    await new Promise<void>((resolve) => {
      const grace = setTimeout(() => {
        this.killChild();
        resolve();
      }, SHUTDOWN_GRACE_MS);
      const child = this.child;
      if (child?.exitCode !== null) { // child 为 null（无进程）或已退出：直接收尾
        clearTimeout(grace);
        resolve();
        return;
      }
      child.once('exit', () => {
        clearTimeout(grace);
        resolve();
      });
      this.killChild();
    });
    await this.pipeServer?.close();
  }

  // ---- 内部状态机 ----

  private setState(state: ServiceState): void {
    this.state = state;
    this.options.onStateChange(state);
    this.options.onEvent({ type: 'service-state', state });
  }

  private handleReady(): void {
    this.policy.recordStart();
    this.heartbeatFailures = 0;
    this.setState('ready');
    this.startHeartbeat();
  }

  private spawnProcess(): void {
    // restarting 提示中间态：手动/崩溃重启都覆盖（unavailable 是 give-up 终态，
    // 手动 restart 从它出发时也要让界面看到「正在拉起」）
    if (this.state === 'ready' || this.state === 'unavailable') this.setState('restarting');
    const target = this.options.pythonTarget ?? resolvePythonTarget(this.options);
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      DRAMACLIP_SERVICE_ADDRESS: this.pipeServer?.address ?? '',
      DRAMACLIP_AUTH_TOKEN: this.token,
      DRAMACLIP_DATA_DIR: this.options.dataDir,
      DRAMACLIP_RESOURCES_DIR: this.options.resourcesDir,
      PYTHONUNBUFFERED: '1',
    };
    this.child = spawn(target.command, [...target.args], {
      cwd: this.options.cwd,
      env,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    this.child.on('error', (error: Error) => {
      console.error(`[ServiceManager] 进程启动失败: ${error.message}`);
      // ENOENT 等启动失败只发 error 不发 exit：不接力 fail 会永远卡在 starting
      if (!this.stopping) this.fail(`进程启动失败: ${error.message}`);
    });
    this.child.stdout?.on('data', (chunk: Buffer) => { this.logLines('info', chunk); });
    this.child.stderr?.on('data', (chunk: Buffer) => { this.logLines('error', chunk); });
    this.child.once('exit', (code: number | null) => {
      this.child = null;
      if (this.stopping) return;
      if (this.manualRespawn) {
        this.manualRespawn = false;
        this.spawnProcess();
        return;
      }
      this.fail(`Python 进程退出(code=${String(code ?? '?')})`);
    });
  }

  private logLines(level: 'info' | 'error', chunk: Buffer): void {
    const text = chunk.toString('utf8');
    if (text.trim().length === 0) return;
    const prefix = level === 'error' ? console.error : console.log;
    prefix(`[service] ${text.trimEnd()}`);
  }

  private fail(reason: string): void {
    this.stopHeartbeat();
    this.killChild();
    const decision = this.policy.onFailure();
    if (decision.action === 'give-up') {
      this.setState('unavailable');
      return;
    }
    console.error(`[ServiceManager] ${reason}，${String(decision.delayMs)}ms 后重启`);
    this.setState('restarting');
    this.restartTimer = setTimeout(() => {
      // child 判空防双拉：断连与进程退出可能先后各触发一次 fail（如手动重启途中）
      if (!this.stopping && this.child === null) this.spawnProcess();
    }, decision.delayMs);
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    const tick = (): void => {
      void this.rpc('system.ping', {}, HEARTBEAT_TIMEOUT_MS)
        .then(() => {
          this.heartbeatFailures = 0;
        })
        .catch(() => {
          this.heartbeatFailures += 1;
          if (this.heartbeatFailures >= HEARTBEAT_MAX_FAILURES && !this.stopping) {
            this.fail(`心跳连续 ${String(this.heartbeatFailures)} 次失败`);
          }
        });
    };
    this.heartbeatTimer = setInterval(tick, HEARTBEAT_INTERVAL_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer !== null) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private killChild(): void {
    if (this.child !== null && this.child.exitCode === null) {
      this.child.kill();
    }
  }

  private clearTimers(): void {
    this.stopHeartbeat();
    if (this.restartTimer !== null) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
  }
}
