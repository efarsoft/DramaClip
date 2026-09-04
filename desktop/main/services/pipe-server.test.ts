// @vitest-environment node
import { randomBytes } from 'node:crypto';
import net from 'node:net';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createLineDecoder } from './ndjson';
import { createPipeServer, type PipeServer } from './pipe-server';

const TOKEN = 't'.repeat(64);

function nextPipePath(): string {
  const suffix = randomBytes(4).toString('hex');
  return process.platform === 'win32'
    ? `\\\\.\\pipe\\dramaclip-test-${suffix}`
    : path.join(tmpdir(), `dramaclip-test-${suffix}.sock`);
}

/** 连接 pipe-server 的测试客户端：行收发。 */
class TestClient {
  readonly socket: net.Socket;
  private readonly decode = createLineDecoder();
  private readonly lines: string[] = [];

  constructor(pipePath: string) {
    this.socket = net.connect(pipePath);
    this.socket.setEncoding('utf8');
    this.socket.on('data', (chunk: string) => {
      this.lines.push(...this.decode(chunk));
    });
  }

  send(payload: unknown): void {
    this.socket.write(`${JSON.stringify(payload)}\n`);
  }

  /** 等到出现第一条满足谓词的行。 */
  async waitForLine(predicate: (message: Record<string, unknown>) => boolean): Promise<Record<string, unknown>> {
    const deadline = Date.now() + 5_000;
    for (;;) {
      while (this.lines.length > 0) {
        const line = this.lines.shift();
        if (line === undefined) break;
        const message = JSON.parse(line) as Record<string, unknown>;
        if (predicate(message)) return message;
      }
      if (Date.now() > deadline) throw new Error('等待行超时');
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
  }

  close(): void {
    this.socket.destroy();
  }
}

const servers: PipeServer[] = [];

afterEach(async () => {
  for (const server of servers.splice(0)) await server.close();
});

function startServer(token = TOKEN): Promise<PipeServer> {
  const server = createPipeServer({
    pipePath: nextPipePath(),
    token,
    appVersion: '2.0.0-test',
    onClientReady: vi.fn(),
    onClientDisconnect: vi.fn(),
    onNotification: vi.fn(),
  });
  servers.push(server);
  return server.listening.then(() => server);
}

describe('createPipeServer', () => {
  it('hello 认证 → call 往返 → 通知上抛', async () => {
    const notifications: [string, Record<string, unknown>][] = [];
    const server = createPipeServer({
      pipePath: nextPipePath(),
      token: TOKEN,
      appVersion: '2.0.0-test',
      onClientReady: vi.fn(),
      onClientDisconnect: vi.fn(),
      onNotification: (method, params) => notifications.push([method, params]),
    });
    servers.push(server);
    await server.listening;

    const client = new TestClient(server.pipePath);
    client.send({ type: 'hello', token: TOKEN, service_version: '2.0.0', protocol_version: 1 });
    const ack = await client.waitForLine((message) => message.type === 'hello-ack');
    expect(ack.app_version).toBe('2.0.0-test');

    const pingPromise = server.call('system.ping', {}, 3_000);
    const request = await client.waitForLine((message) => message.method === 'system.ping');
    client.send({ jsonrpc: '2.0', id: request.id, result: { service_version: '2.0.0' } });
    await expect(pingPromise).resolves.toEqual({ service_version: '2.0.0' });

    client.send({ jsonrpc: '2.0', method: 'log.append', params: { level: 'info', message: 'hi' } });
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(notifications).toEqual([['log.append', { level: 'info', message: 'hi' }]]);

    client.close();
  });

  it('错误 token → 连接被销毁，call 不可用', async () => {
    const server = await startServer();
    const client = new TestClient(server.pipePath);
    const closed = new Promise<void>((resolve) => client.socket.once('close', () => { resolve(); }));
    client.send({ type: 'hello', token: 'wrong-token', service_version: 'x', protocol_version: 1 });
    await closed;
    await expect(server.call('system.ping', {}, 500)).rejects.toThrow('未连接');
    client.close();
  });

  it('未认证连接不允许 RPC', async () => {
    const server = await startServer();
    const client = new TestClient(server.pipePath);
    const closed = new Promise<void>((resolve) => client.socket.once('close', () => { resolve(); }));
    client.send({ jsonrpc: '2.0', id: '1', method: 'system.ping', params: {} }); // 未先 hello
    await closed;
    client.close();
  });
});
