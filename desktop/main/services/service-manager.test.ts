/** resolvePythonTarget：开发=venv python -m；打包=resources 内 onedir sidecar。 */
import { mkdtempSync, mkdirSync, closeSync, openSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { resolvePythonTarget, type ServiceManagerOptions } from './service-manager';

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
