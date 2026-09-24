// @vitest-environment node
/** resolvePythonTarget：开发=venv python -m；打包=resources 内 onedir sidecar。
 * 生命周期：give-up 后手动 restart 直接重拉（修复点）、ready 态手动重启不走退避。 */
import { existsSync, mkdtempSync, mkdirSync, closeSync, openSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import type { ServiceState } from '@dramaclip/protocol';
import {
  ServiceManager,
  resolvePythonTarget,
  type ServiceManagerOptions,
} from './service-manager';
import { RestartPolicy } from './restart-policy';

function makeOptions(overrides: Partial<ServiceManagerOptions> = {}): ServiceManagerOptions {
  return {
    repoRoot: 'D:/repo',
    resourcesDir: 'D:/repo/resources',
    cwd: 'D:/repo',
    dataDir: 'D:/repo/data',
    appVersion: '0.0.0-test',
    isPackaged: false,
    onStateChange: () => undefined,
    onEvent: () => undefined,
    ...overrides,
  };
}

describe('resolvePythonTarget', () => {
  it('打包模式指向 resources/dramaclip-service onedir 产物', () => {
    const target = resolvePythonTarget(makeOptions({ isPackaged: true }));
    expect(target.command).toBe(
      path.join('D:/repo/resources', 'dramaclip-service', 'dramaclip-service.exe'),
    );
    expect(target.args).toHaveLength(0);
  });

  it('开发模式存在 venv 时优先使用并以 -m dramaclip 启动', () => {
    const repoRoot = mkdtempSync(path.join(tmpdir(), 'dc-sm-'));
    const rel = process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python';
    const venvPython = path.join(repoRoot, '.venv', rel);
    mkdirSync(path.dirname(venvPython), { recursive: true });
    closeSync(openSync(venvPython, 'w'));
    const target = resolvePythonTarget(makeOptions({ repoRoot }));
    expect(target.command).toContain('.venv');
    expect(target.args).toEqual(['-m', 'dramaclip']);
  });

  it('开发模式无 venv 时回退 PATH 中的 python', () => {
    const target = resolvePythonTarget(makeOptions({ repoRoot: 'D:/no-such-repo' }));
    expect(target.command).toBe('python');
    expect(target.args).toEqual(['-m', 'dramaclip']);
  });
});

describe('ServiceManager 生命周期（假服务夹具）', () => {
  const fixture = fileURLToPath(new URL('./__fixtures__/fake-service.mjs', import.meta.url));
  // 某些环境下 vitest worker 的 execPath 指向已不存在的 node 装置（ENOENT），
  // 此时退回 PATH 里的 node——夹具只要求任何能跑 .mjs 的 node
  const nodeCommand = existsSync(process.execPath) ? process.execPath : 'node';

  function makeManager(): ServiceManager {
    // cwd 必须真实存在：Windows 上 spawn 对不存在的 cwd 报 ENOENT（且误指到 exe 名）
    const root = mkdtempSync(path.join(tmpdir(), 'dc-life-'));
    return new ServiceManager(makeOptions({
      repoRoot: root,
      cwd: root,
      dataDir: path.join(root, 'data'),
      pythonTarget: { command: nodeCommand, args: [fixture] },
      // 0 次重试、退避 10ms：首崩即 give-up，把真实策略压进毫秒级
      policy: new RestartPolicy(0, 1_000, 10),
    }));
  }

  async function untilState(manager: ServiceManager, want: ServiceState, timeoutMs = 15_000): Promise<void> {
    const deadline = Date.now() + timeoutMs;
    while (manager.currentState !== want) {
      if (Date.now() > deadline) {
        throw new Error(`等待状态 ${want} 超时，当前 ${manager.currentState}`);
      }
      await new Promise((resolve) => { setTimeout(resolve, 25); });
    }
  }

  it('give-up 后手动 restart 直接重拉：unavailable → ready（修复点）', async () => {
    const manager = makeManager();
    await manager.start();
    await untilState(manager, 'ready');
    await manager.rpc('crash.now', {}).catch(() => undefined); // 崩溃可能先断连接再回包
    await untilState(manager, 'unavailable');
    manager.restart();
    await untilState(manager, 'ready');
    await manager.stop();
  }, 30_000);

  it('ready 态手动 restart：exit 事件接力立即重拉，清账不进退避', async () => {
    const manager = makeManager();
    await manager.start();
    await untilState(manager, 'ready');
    manager.restart();
    await untilState(manager, 'ready');
    await manager.stop();
  }, 30_000);
});
