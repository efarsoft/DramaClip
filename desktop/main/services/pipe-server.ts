/**
 * 本地套接字服务端（ADR-002 修订版）：127.0.0.1 环回 TCP，NDJSON 分帧。
 * 单连接；hello(token) 认证；request/response 按 id 关联；notification 上抛。
 * 不 import electron（appVersion 经参数注入）——可在 node 环境单测。
 * 为何非命名管道：Python CRT 管道句柄并发读写会死锁写方（详见 docs/00 ADR-002）。
 */
import net from 'node:net';
import { createLineDecoder } from './ndjson';

export const MAX_LINE_BYTES = 16 * 1024 * 1024;
const HELLO_TIMEOUT_MS = 10_000;
const DEFAULT_CALL_TIMEOUT_MS = 30_000;

export interface HelloInfo {
  readonly service_version: string;
  readonly protocol_version: number;
}

export interface PipeServerOptions {
  readonly token: string;
  readonly appVersion: string;
  readonly onClientReady: (hello: HelloInfo) => void;
  readonly onClientDisconnect: () => void;
  readonly onNotification: (method: string, params: Record<string, unknown>) => void;
}

export interface PipeServer {
  /** 监听地址（host:port，listening 解决后有效）。 */
  readonly address: string;
  /** server 进入 listening 的 promise（失败即 reject）。 */
  readonly listening: Promise<void>;
  call(method: string, params: Record<string, unknown>, timeoutMs?: number): Promise<unknown>;
  sendNotification(method: string, params: Record<string, unknown>): void;
  close(): Promise<void>;
}

interface PendingCall {
  resolve(value: unknown): void;
  reject(error: Error): void;
  timer: NodeJS.Timeout;
}

class PipeServerImpl implements PipeServer {
  readonly listening: Promise<void>;
  private addressValue = '';
  private readonly options: PipeServerOptions;
  private readonly pending = new Map<string, PendingCall>();
  private readonly decode = createLineDecoder();
  private readonly server: net.Server;
  private socket: net.Socket | null = null;
  private authed = false;
  private nextId = 0;
  private helloTimer: NodeJS.Timeout | null = null;

  constructor(options: PipeServerOptions) {
    this.options = options;
    this.server = net.createServer((client: net.Socket) => {
      this.acceptClient(client);
    });
    this.listening = new Promise<void>((resolveListen, rejectListen) => {
      this.server.once('listening', () => {
        const bound = this.server.address();
        if (bound !== null) this.addressValue = formatAddress(bound);
        resolveListen();
      });
      this.server.once('error', (error: Error) => {
        rejectListen(error);
      });
    });
    // 端口 0 = 系统随机分配；仅环回绑定，不触发防火墙弹窗
    this.server.listen(0, '127.0.0.1');
  }

  get address(): string {
    return this.addressValue;
  }

  private acceptClient(client: net.Socket): void {
    if (this.socket !== null && !this.socket.destroyed) client.destroy(); // 单连接
    this.socket = client;
    this.authed = false;
    client.setEncoding('utf8');
    this.helloTimer = setTimeout(() => client.destroy(), HELLO_TIMEOUT_MS);
    client.on('data', (chunk: string) => {
      for (const line of this.decode(chunk)) this.handleLine(line);
    });
    client.on('error', () => client.destroy());
    client.on('close', () => {
      this.handleDisconnect();
    });
  }

  private handleLine(line: string): void {
    if (line.length > MAX_LINE_BYTES) {
      this.socket?.destroy();
      return;
    }
    let message: Record<string, unknown>;
    try {
      message = JSON.parse(line) as Record<string, unknown>;
    } catch {
      this.socket?.destroy();
      return;
    }
    if (message.type === 'hello') {
      this.handleHello(message);
      return;
    }
    if (!this.authed) {
      this.socket?.destroy(); // 认证前只接受 hello
      return;
    }
    if (typeof message.method === 'string') {
      if (message.id === undefined) {
        this.options.onNotification(message.method, asParams(message.params));
      } else {
        this.replyMethodNotFound(message.id); // W1：主进程不接收 Python 侧请求
      }
      return;
    }
    this.settlePending(message);
  }

  private handleHello(message: Record<string, unknown>): void {
    const serviceVersion = message.service_version;
    const protocolVersion = message.protocol_version;
    const valid =
      message.token === this.options.token &&
      typeof serviceVersion === 'string' &&
      typeof protocolVersion === 'number';
    if (!valid) {
      this.socket?.destroy();
      return;
    }
    this.authed = true;
    if (this.helloTimer !== null) clearTimeout(this.helloTimer);
    this.writeJson({ type: 'hello-ack', app_version: this.options.appVersion });
    this.options.onClientReady({
      service_version: serviceVersion,
      protocol_version: protocolVersion,
    });
  }

  private settlePending(message: Record<string, unknown>): void {
    const id = message.id;
    if (typeof id !== 'string') return;
    const entry = this.pending.get(id);
    if (entry === undefined) return;
    this.pending.delete(id);
    clearTimeout(entry.timer);
    const error = message.error as { code?: number; message?: string } | undefined;
    if (error !== undefined) {
      entry.reject(new Error(`[${String(error.code ?? -1)}] ${error.message ?? '未知错误'}`));
      return;
    }
    entry.resolve(message.result);
  }

  private replyMethodNotFound(id: unknown): void {
    this.writeJson({ jsonrpc: '2.0', id, error: { code: -32601, message: '方法不存在' } });
  }

  private writeJson(payload: unknown): boolean {
    if (this.socket === null || this.socket.destroyed) return false;
    this.socket.write(`${JSON.stringify(payload)}\n`);
    return true;
  }

  private handleDisconnect(): void {
    if (this.helloTimer !== null) {
      clearTimeout(this.helloTimer);
      this.helloTimer = null;
    }
    this.socket = null;
    const wasAuthed = this.authed;
    this.authed = false;
    for (const entry of this.pending.values()) {
      clearTimeout(entry.timer);
      entry.reject(new Error('连接断开'));
    }
    this.pending.clear();
    if (wasAuthed) this.options.onClientDisconnect();
  }

  call(
    method: string,
    params: Record<string, unknown>,
    timeoutMs: number = DEFAULT_CALL_TIMEOUT_MS,
  ): Promise<unknown> {
    return new Promise((resolve, reject) => {
      if (this.socket === null || this.socket.destroyed || !this.authed) {
        reject(new Error('Python 服务未连接'));
        return;
      }
      this.nextId += 1;
      const id = `c${String(this.nextId)}`;
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`RPC 超时: ${method}`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.writeJson({ jsonrpc: '2.0', id, method, params });
    });
  }

  sendNotification(method: string, params: Record<string, unknown>): void {
    this.writeJson({ jsonrpc: '2.0', method, params });
  }

  close(): Promise<void> {
    return new Promise((resolveClose) => {
      for (const entry of this.pending.values()) {
        clearTimeout(entry.timer);
        entry.reject(new Error('服务端关闭'));
      }
      this.pending.clear();
      this.socket?.destroy();
      this.server.close(() => {
        resolveClose();
      });
    });
  }
}

function asParams(raw: unknown): Record<string, unknown> {
  return typeof raw === 'object' && raw !== null ? (raw as Record<string, unknown>) : {};
}

function formatAddress(address: net.AddressInfo | string): string {
  if (typeof address === 'string') return address;
  return `${address.address}:${String(address.port)}`;
}

export function createPipeServer(options: PipeServerOptions): PipeServer {
  return new PipeServerImpl(options);
}
