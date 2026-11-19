// @vitest-environment node
/** 卸载器注册表写入守卫：数据目录真值是 NSIS「删除模型与运行环境」选项的
 * 定位依据——打包态 win32 才写；dev 态（仓库 data/）与非 win32 不写；
 * spawn error 事件不冒泡炸进程。 */
import { describe, expect, it, vi } from 'vitest';
import type { spawn as SpawnType } from 'node:child_process';
import { registerDataDirForUninstaller } from './uninstaller-reg';

function fakeSpawn(): ReturnType<typeof vi.fn> {
  const fn = vi.fn(() => ({ on: vi.fn() }));
  return fn;
}

describe('registerDataDirForUninstaller', () => {
  it('打包态 win32 写 HKCU DataDir', () => {
    const run = fakeSpawn() as unknown as typeof SpawnType;
    registerDataDirForUninstaller('D:\\data', true, 'win32', run);
    expect(run).toHaveBeenCalledOnce();
    const args = (run as unknown as ReturnType<typeof vi.fn>).mock
      .calls[0] as unknown as string[];
    expect(args[0]).toBe('reg');
    expect(args[1]).toContain('HKCU\\Software\\DramaClip');
    expect(args[1]).toContain('/d');
    expect(args[1]).toContain('D:\\data');
  });

  it('dev 态不写（仓库 data/ 不进卸载语义）', () => {
    const run = fakeSpawn() as unknown as typeof SpawnType;
    registerDataDirForUninstaller('D:\\repo\\data', false, 'win32', run);
    expect(run).not.toHaveBeenCalled();
  });

  it('非 win32 不写', () => {
    const run = fakeSpawn() as unknown as typeof SpawnType;
    registerDataDirForUninstaller('/home/u/data', true, 'linux', run);
    expect(run).not.toHaveBeenCalled();
  });

  it('spawn error 事件静默（注册表不可写不阻断启动）', () => {
    const on = vi.fn();
    const run = (() => {
      return { on };
    }) as unknown as typeof SpawnType;
    expect(() => {
      registerDataDirForUninstaller('D:\\data', true, 'win32', run);
    }).not.toThrow();
    expect(on).toHaveBeenCalledWith('error', expect.any(Function));
  });
});
