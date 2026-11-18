// @vitest-environment node
/** ipcMain 通道登记守卫（W13·ipc.ts 零测试缺口收口）：
 *  ① 通道清单与登记次数（每通道恰好一个 handle）；
 *  ② rpc 通道白名单：未知方法拒绝、已知方法转发；
 *  ③ copyFiles 撞名 -1 后缀不吞别人文件；
 *  ④ broadcastEvent 逐窗广播。electron 全 mock（main 代码不在 jsdom 跑）。 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Mock } from 'vitest';

const handles = new Map<string, Mock>();

vi.mock('electron', () => ({
  ipcMain: {
    handle: vi.fn((channel: string, handler: Mock) => {
      handles.set(channel, handler);
    }),
  },
  BrowserWindow: { fromWebContents: vi.fn(() => null) },
  app: { getPath: vi.fn(() => 'C:\\userData') },
  shell: { showItemInFolder: vi.fn() },
}));

vi.mock('../services/storage', () => ({
  freeBytes: vi.fn(() => Promise.resolve(1 << 30)),
  loadAppConfig: vi.fn(() => ({})),
  lowDiskHintActive: vi.fn(() => false),
  migrateDataDir: vi.fn(() => Promise.resolve({ moved: [], skipped: [] })),
  saveAppConfig: vi.fn(),
  storageUsage: vi.fn(() => Promise.resolve({ used: 1 })),
}));

vi.mock('../services/dialog', () => ({
  pickFolder: vi.fn(),
  pickVideoFile: vi.fn(),
  pickAudioFile: vi.fn(),
  saveTextFile: vi.fn(),
}));

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import type { IpcContext } from './ipc';
import { broadcastEvent, registerIpc, resolveDataPaths } from './ipc';

const context = {
  rpc: vi.fn((method: string) => Promise.resolve({ method, ok: true })),
  restartService: vi.fn(),
  appVersion: () => '0.2.5',
  dataPaths: () => resolveDataPaths('C:\\data'),
  windows: () => [],
};

beforeEach(() => {
  handles.clear();
  registerIpc(context);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('resolveDataPaths', () => {
  it('五个锚点全部落在 dataDir 下（ADR-009 同名约定）', () => {
    const paths = resolveDataPaths('C:\\data');
    expect(paths.root).toBe('C:\\data');
    for (const key of ['outputs', 'models', 'logs', 'trash'] as const) {
      expect(paths[key].startsWith('C:\\data')).toBe(true);
    }
  });
});

describe('通道登记清单', () => {
  it('每通道恰好登记一个 handle，无重复无遗漏', () => {
    const expected = [
      'rpc',
      'app:version',
      'app:paths',
      'app:relaunch',
      'window:control',
      'dialog:pickFolder',
      'dialog:pickVideoFile',
      'dialog:pickAudioFile',
      'dialog:saveTextFile',
      'shell:reveal',
      'shell:copyFiles',
      'service:restart',
      'storage:info',
      'storage:migrate',
      'storage:dismissHint',
    ];
    expect([...handles.keys()].sort()).toEqual(expected.slice().sort());
  });
});

describe('rpc 通道白名单', () => {
  const callRpc = async (method: unknown, params: unknown = {}): Promise<unknown> => {
    const handler = handles.get('rpc');
    if (handler === undefined) throw new Error('rpc 通道未登记');
    return await handler(null, method, params);
  };

  it('未知方法直接拒绝，不转发给服务端', async () => {
    await expect(callRpc('not_a_method')).rejects.toThrow('未知 RPC 方法');
    expect(context.rpc).not.toHaveBeenCalled();
  });

  it('已知方法原样转发且 params 非对象时兜成空对象', async () => {
    const result = (await callRpc('jobs.list', { limit: 5 })) as { method: string };
    expect(result.method).toBe('jobs.list');
    expect(context.rpc).toHaveBeenCalledWith('jobs.list', { limit: 5 });
    await callRpc('jobs.list', '脏参数');
    expect(context.rpc).toHaveBeenLastCalledWith('jobs.list', {});
  });
});

describe('shell:copyFiles 撞名后缀', () => {
  it('同名文件加 -1 后缀，不覆盖既有文件', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ipc-test-'));
    try {
      const srcA = path.join(dir, 'a.txt');
      const srcB = path.join(dir, 'b.txt');
      fs.writeFileSync(srcA, 'first');
      fs.writeFileSync(srcB, 'second');
      const destDir = path.join(dir, 'dest');
      fs.mkdirSync(destDir);
      const existing = path.join(destDir, 'a.txt');
      fs.writeFileSync(existing, 'do-not-overwrite');

      const handler = handles.get('shell:copyFiles');
      const result = (await handler?.(null, [srcA, srcB], destDir)) as {
        copied: string[];
        failed: unknown[];
      };
      expect(result.failed).toEqual([]);
      expect(fs.readFileSync(path.join(destDir, 'a.txt'), 'utf8')).toBe('do-not-overwrite');
      expect(fs.readFileSync(path.join(destDir, 'a-1.txt'), 'utf8')).toBe('first');
      expect(fs.readFileSync(path.join(destDir, 'b.txt'), 'utf8')).toBe('second');
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe('broadcastEvent', () => {
  it('逐窗广播：windows() 的每个目标各收到一份事件', () => {
    const sent: string[] = [];
    const makeWindow = (name: string) => ({
      isDestroyed: () => false,
      webContents: {
        send: (channel: string, payload: unknown) => {
          sent.push(`${name}:${channel}:${(payload as { method: string }).method}`);
        },
      },
    });
    const targets = [makeWindow('a'), makeWindow('b')];
    const ctx = { ...context, windows: () => targets };
    broadcastEvent(ctx as unknown as IpcContext, {
      type: 'notification',
      method: 'models.download_progress',
      params: {},
    });
    expect(sent).toEqual([
      'a:service:event:models.download_progress',
      'b:service:event:models.download_progress',
    ]);
  });
});
