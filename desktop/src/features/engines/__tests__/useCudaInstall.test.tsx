// @vitest-environment jsdom
/**
 * CUDA 运行库安装动作盯的是安装作业：收尾即停表。
 *
 * 此前盯的是状态——「装着就每 2 秒重探、探到已安装才停」，装失败时状态永远到不了
 * 已安装，重探永不停，总览那一行也一直挂在安装中。这里用假定时器钉住「停」。
 */
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { JobInfo } from '@dramaclip/protocol';
import { jobsApi, runtimeApi } from '../../../services/client';
import { useCudaInstall } from '../useCudaInstall';

vi.mock('../../../services/client', () => ({
  jobsApi: {
    get: vi.fn(() => Promise.resolve({ job: { id: 'c', progress: 0, label: '', status: 'running' } })),
  },
  runtimeApi: {
    install: vi.fn(() => Promise.resolve({ job_id: 'c' })),
  },
}));

const job = (status: JobInfo['status'], error: string | null = null): JobInfo => ({
  id: 'c',
  type: 'cuda_runtime',
  ref_id: null,
  status,
  progress: 50,
  label: '',
  error,
  created_at: 0,
  updated_at: 0,
});

/** 让已决议的 promise 链与随之触发的渲染/副作用都落地。 */
const settle = async (): Promise<void> => {
  await act(async () => {
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
  });
};

const advance = async (ms: number): Promise<void> => {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
  await settle();
};

describe('useCudaInstall', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('装成 → 重探一次，然后停表', async () => {
    vi.mocked(jobsApi.get)
      .mockResolvedValueOnce({ job: job('running') })
      .mockResolvedValueOnce({ job: job('completed') });
    const reload = vi.fn();
    const { result } = renderHook(() => useCudaInstall(reload));

    act(() => {
      result.current.start();
    });
    await settle();
    expect(result.current.installing).toBe(true);
    expect(jobsApi.get).toHaveBeenCalledTimes(1); // 起作业后先查一次，不等一轮间隔

    await advance(2000);
    expect(result.current.installing).toBe(false);
    expect(result.current.problem).toBe('');
    expect(reload).toHaveBeenCalledTimes(1);

    await advance(60000);
    expect(jobsApi.get).toHaveBeenCalledTimes(2);
  });

  it('作业失败 → 原因常驻并停表，不再每 2 秒重探', async () => {
    vi.mocked(jobsApi.get).mockResolvedValue({ job: job('failed', '镜像源全部超时') });
    const reload = vi.fn();
    const { result } = renderHook(() => useCudaInstall(reload));

    act(() => {
      result.current.start();
    });
    await settle();
    expect(result.current.installing).toBe(false);
    expect(result.current.problem).toBe('CUDA 运行库下载失败：镜像源全部超时');

    await advance(60000);
    expect(jobsApi.get).toHaveBeenCalledTimes(1);
    expect(reload).not.toHaveBeenCalled();
  });

  it('作业被取消 → 说「已取消」，不冒充失败', async () => {
    vi.mocked(jobsApi.get).mockResolvedValue({ job: job('cancelled') });
    const { result } = renderHook(() => useCudaInstall(vi.fn()));

    act(() => {
      result.current.start();
    });
    await settle();

    expect(result.current.problem).toBe('CUDA 运行库安装已取消');
    expect(result.current.installing).toBe(false);
  });

  it('没启起来 → 不起轮询', async () => {
    vi.mocked(runtimeApi.install).mockRejectedValue(new Error('磁盘空间不足'));
    const { result } = renderHook(() => useCudaInstall(vi.fn()));

    act(() => {
      result.current.start();
    });
    await settle();
    await advance(60000);

    expect(result.current.problem).toBe('CUDA 运行库下载失败：磁盘空间不足');
    expect(jobsApi.get).not.toHaveBeenCalled();
  });
});
