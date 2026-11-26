// @vitest-environment jsdom
/**
 * GPU 探测：文件头一直写着「5s 轮询，就绪即停」，代码却从不停——引擎页开着就每 5 秒
 * 问一次 system.health（这条慢的时候要七八秒）。这里钉住「探到即停、没探到才继续问」。
 */
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { GpuInfo, HealthResult } from '@dramaclip/protocol';
import { systemApi } from '../../../services/client';
import { useUiStore } from '../../../stores/ui';
import { useGpuInfo } from '../useGpuInfo';

vi.mock('../../../services/client', () => ({
  systemApi: { health: vi.fn(() => Promise.resolve({ gpu_info: null })) },
}));

const READY: GpuInfo = {
  ready: true,
  vendor: 'nvidia',
  name: 'RTX 4060',
  driver_version: '572.10',
  max_cuda_version: '12.8',
  memory_total_mb: 8188,
  compute_cap: '8.9',
};

const PROBING: GpuInfo = { ...READY, ready: false, name: '', driver_version: '' };

const settle = async (): Promise<void> => {
  await act(async () => {
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
  });
};

const health = (gpu_info: GpuInfo | undefined): HealthResult =>
  ({ status: 'ok', uptime_s: 1, ffmpeg_version: '7.1', gpu_info });

const advance = async (ms: number): Promise<void> => {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
  await settle();
};

describe('useGpuInfo', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    useUiStore.setState({ serviceState: 'ready' });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('探到结果即停：引擎页开着也不再问', async () => {
    vi.mocked(systemApi.health).mockResolvedValue(health(READY));
    const { result } = renderHook(() => useGpuInfo());
    await settle();

    expect(result.current.info?.name).toBe('RTX 4060');
    await advance(60000);
    expect(systemApi.health).toHaveBeenCalledTimes(1);
  });

  it('还没探到 → 每 5 秒继续问，直到就绪', async () => {
    vi.mocked(systemApi.health)
      .mockResolvedValueOnce(health(undefined))
      .mockResolvedValueOnce(health(PROBING))
      .mockResolvedValue(health(READY));
    const { result } = renderHook(() => useGpuInfo());
    await settle();
    expect(systemApi.health).toHaveBeenCalledTimes(1);

    await advance(5000);
    expect(systemApi.health).toHaveBeenCalledTimes(2);
    expect(result.current.info?.ready).toBe(false);

    await advance(5000);
    expect(result.current.info?.ready).toBe(true);
    await advance(60000);
    expect(systemApi.health).toHaveBeenCalledTimes(3);
  });
});
