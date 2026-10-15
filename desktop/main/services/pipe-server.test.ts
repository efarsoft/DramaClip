// @vitest-environment node
import net from 'node:net';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createLineDecoder } from './ndjson';
import { createPipeServer, type PipeServer } from './pipe-server';

const TOKEN = 't'.repeat(64);

/** 连接 pipe-server 的测试客户端：行收发。 */
class TestClient {
  readonly socket: net.Socket;
  private readonly decode = createLineDecoder();
  private readonly lines: string[] = [];

  constructor(address: string) {
    const [host, port] = address.split(':');
    const portNumber = Number(port ?? '0');
    this.socket = net.connect(portNumber, host);
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
      token: TOKEN,
      appVersion: '2.0.0-test',
      onClientReady: vi.fn(),
      onClientDisconnect: vi.fn(),
      onNotification: (method, params) => notifications.push([method, params]),
    });
    servers.push(server);
    await server.listening;

    const client = new TestClient(server.address);
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
    const client = new TestClient(server.address);
    const closed = new Promise<void>((resolve) => client.socket.once('close', () => { resolve(); }));
    client.send({ type: 'hello', token: 'wrong-token', service_version: 'x', protocol_version: 1 });
    await closed;
    await expect(server.call('system.ping', {}, 500)).rejects.toThrow('未连接');
    client.close();
  });

  it('未认证连接不允许 RPC', async () => {
    const server = await startServer();
    const client = new TestClient(server.address);
    const closed = new Promise<void>((resolve) => client.socket.once('close', () => { resolve(); }));
    client.send({ jsonrpc: '2.0', id: '1', method: 'system.ping', params: {} }); // 未先 hello
    await closed;
    client.close();
  });

  it('第二条连接顶不掉在用的认证连接', async () => {
    // 回归钉：旧实现在 destroy 后来者后继续执行，把 this.socket 换成了这条已销毁的
    // 假连接——真服务的响应再也收不到，pending 全判超时，还顺带误报一次断连。
    const disconnected = vi.fn();
    const server = createPipeServer({
      token: TOKEN,
      appVersion: '2.0.0-test',
      onClientReady: vi.fn(),
      onClientDisconnect: disconnected,
      onNotification: vi.fn(),
    });
    servers.push(server);
    await server.listening;

    const first = new TestClient(server.address);
    first.send({ type: 'hello', token: TOKEN, service_version: '2.0.0', protocol_version: 1 });
    await first.waitForLine((message) => message.type === 'hello-ack');

    const second = new TestClient(server.address);
    const rejected = new Promise<void>((resolve) => {
      second.socket.on('close', () => { resolve(); });
    });
    second.socket.on('error', () => undefined); // 立刻被拒时客户端可能吃到 ECONNRESET
    second.send({ type: 'hello', token: TOKEN, service_version: '2.0.0', protocol_version: 1 });
    await rejected;

    const ping = server.call('system.ping', {}, 3_000);
    const request = await first.waitForLine((message) => message.method === 'system.ping');
    first.send({ jsonrpc: '2.0', id: request.id, result: { pong: 1 } });
    await expect(ping).resolves.toEqual({ pong: 1 });
    expect(disconnected).not.toHaveBeenCalled();

    first.close();
    second.close();
  });

  it('上一条连接的残帧不混进新连接的请求', async () => {
    // 回归钉：分帧器曾是服务端实例级共享——A 没收完的半行会接到 B 的字节上，
    // 拼出一条 B 从未发过的请求（伪造通知/串号响应都从这里来）。
    const notifications: string[] = [];
    const server = createPipeServer({
      token: TOKEN,
      appVersion: '2.0.0-test',
      onClientReady: vi.fn(),
      onClientDisconnect: vi.fn(),
      onNotification: (method) => { notifications.push(method); },
    });
    servers.push(server);
    await server.listening;

    const first = new TestClient(server.address);
    first.send({ type: 'hello', token: TOKEN, service_version: '2.0.0', protocol_version: 1 });
    await first.waitForLine((message) => message.type === 'hello-ack');
    first.socket.write('{"jsonrpc":"2.0","method":"log.append"'); // 故意不写完一行
    const firstClosed = new Promise<void>((resolve) => {
      first.socket.on('close', () => { resolve(); });
    });
    first.socket.on('error', () => undefined);
    first.close();
    await firstClosed;

    const second = new TestClient(server.address);
    second.send({ type: 'hello', token: TOKEN, service_version: '2.0.0', protocol_version: 1 });
    await second.waitForLine((message) => message.type === 'hello-ack');
    second.socket.write(',"params":{"message":"forged"}}\n'); // 续上 A 的半行
    await new Promise((resolve) => setTimeout(resolve, 150));

    expect(notifications).toEqual([]);
    second.close();
  });
});
