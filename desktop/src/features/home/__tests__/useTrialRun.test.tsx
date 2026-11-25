/** 零配置试跑编排钉：免文案链（分析跳过→规划→导出）状态机与断点语义。
 *
 *  夹具按服务端的真实形状写：集列表的行键是 `episode_id`（协议 EpisodeAnalysisResult），
 *  没有 `id`——夹具曾自带 `id`，把「取错键、提交 [null]」这个真 bug 一起测没了
 *  （2026-11-24 审查实锤：真机上分析阶段必报「episode_ids 含无效项」）。
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useTrialRun } from '../useTrialRun';

type RpcReply =
  | { episodes: { episode_id: string; episode_number: number; status: string }[] }
  | { job_id: string; k?: number; batch_id?: string }
  | { id: string }[]
  | { exports: { plan_id: string; export_id: string; job_id: string }[]; rejected: { plan_id: string; reason: string }[] }
  | { job: { id: string; type: string; ref_id: null; status: string; progress: number } }
  | { status: string; progress: number; message?: string; error?: string };

const rpcMock = vi.fn<(method: string, params?: unknown) => Promise<RpcReply>>();
vi.mock('../../../services/client', () => ({
  analysisApi: {
    episodes: (projectId: string) => rpcMock('analysis.episodes', { project_id: projectId }),
    start: (projectId: string, episodeIds: readonly string[]) =>
      rpcMock('analysis.start', { project_id: projectId, episode_ids: episodeIds }),
    status: (jobId: string) => rpcMock('analysis.status', { job_id: jobId }),
  },
  narrationApi: {
    planVariants: (projectId: string, modes: string[], k: number) =>
      rpcMock('narration.plan_variants', { project_id: projectId, modes, k }),
    listPlans: (projectId: string, batchId?: string) =>
      rpcMock('narration.list_plans', { project_id: projectId, batch_id: batchId }),
  },
  exportApi: { submit: (planIds: string[]) => rpcMock('export.submit', { plan_ids: planIds }) },
  jobsApi: { get: (jobId: string) => rpcMock('jobs.get', { job_id: jobId }) },
}));

function rpcReply(method: string): RpcReply {
  switch (method) {
    case 'analysis.episodes':
      return { episodes: [{ episode_id: 'ep2', episode_number: 2, status: 'done' }, { episode_id: 'ep1', episode_number: 1, status: 'done' }] };
    case 'narration.plan_variants':
      return { job_id: 'j-plan', k: 1, batch_id: 'batch-1' };
    case 'narration.list_plans':
      return [{ id: 'plan-1' }];
    case 'export.submit':
      return { exports: [{ plan_id: 'plan-1', export_id: 'exp-1', job_id: 'j-exp' }], rejected: [] };
    case 'jobs.get':
      // jobsApi.get 返回 { job } 包层（服务端 jobs.get 的返回形状）
      return { job: { id: 'j-exp', type: 'export', ref_id: null, status: 'completed', progress: 100 } };
    default:
      return { status: 'completed', progress: 100, message: '' };
  }
}

afterEach(() => {
  rpcMock.mockClear();
});

describe('useTrialRun', () => {
  it('免文案全链跑通：选集号最小的一集、分析已 done 跳过、终态 done', async () => {
    rpcMock.mockImplementation((method: string) => Promise.resolve(rpcReply(method)));
    const { result } = renderHook(() => useTrialRun('proj-1'));
    await act(async () => {
      await result.current.start();
    });

    await waitFor(() => {
      expect(result.current.phase.kind).toBe('done')
    });
    const startCall = rpcMock.mock.calls.find((c) => c[0] === 'analysis.start');
    expect(startCall).toBeUndefined(); // 两集都 done：分析阶段整段跳过
    const planCall = rpcMock.mock.calls.find((c) => c[0] === 'narration.plan_variants');
    expect(planCall?.[1]).toMatchObject({ project_id: 'proj-1', modes: ['raw_clip'], k: 1 });
    const submitCall = rpcMock.mock.calls.find((c) => c[0] === 'export.submit');
    expect(submitCall?.[1]).toEqual({ plan_ids: ['plan-1'] });
    if (result.current.phase.kind === 'done') {
      expect(result.current.phase.exportId).toBe('exp-1');
    }
  });

  it('导出被拒：export.submit 的 rejected 带人读理由进 failed 阶段', async () => {
    rpcMock.mockImplementation((method: string): Promise<RpcReply> => {
      if (method === 'analysis.episodes') {
        return Promise.resolve({
          episodes: [{ episode_id: 'ep1', episode_number: 1, status: 'done' }],
        });
      }
      if (method === 'export.submit') {
        const rejectedPack = {
          exports: [] as { plan_id: string; export_id: string; job_id: string }[],
          rejected: [{ plan_id: 'plan-1', reason: '方案没有可渲染的时间轴' }],
        };
        return Promise.resolve(rejectedPack);
      }
      return Promise.resolve(rpcReply(method));
    });
    const { result } = renderHook(() => useTrialRun('proj-1'));
    await act(async () => {
      await result.current.start();
    });
    await waitFor(() => {
      expect(result.current.phase.kind).toBe('failed');
    });
    if (result.current.phase.kind === 'failed') {
      expect(result.current.phase.stage).toBe('export');
      expect(result.current.phase.reason).toContain('方案没有可渲染的时间轴');
    }
  });

  it('项目没有已导入素材：no-material 不发任何任务', async () => {
    rpcMock.mockImplementation((method: string) => {
      if (method === 'analysis.episodes') {
        return Promise.resolve({ episodes: [] });
      }
      return Promise.resolve(rpcReply(method));
    });
    const { result } = renderHook(() => useTrialRun('proj-1'));
    await act(async () => {
      await result.current.start();
    });

    await waitFor(() => {
      expect(result.current.phase.kind).toBe('no-material')
    });
    expect(rpcMock.mock.calls.some((c) => c[0] === 'narration.plan_variants')).toBe(false);
  });

  it('分析失败：failed 带阶段与原因，重试从失败阶段重入', async () => {
    let analysisCalls = 0;
    rpcMock.mockImplementation((method: string): Promise<RpcReply> => {
      if (method === 'analysis.episodes') {
        return Promise.resolve({
          episodes: [{ episode_id: 'ep1', episode_number: 1, status: 'pending' }],
        });
      }
      if (method === 'analysis.start') {
        analysisCalls += 1;
        return Promise.resolve({ job_id: 'j-ana' });
      }
      if (method === 'analysis.status') {
        // 第一次轮询失败、重试后成功
        return Promise.resolve(
          analysisCalls === 1
            ? { status: 'failed', progress: 40, error: '显存不够' }
            : { status: 'completed', progress: 100, message: '' },
        );
      }
      return Promise.resolve(rpcReply(method));
    });
    const { result } = renderHook(() => useTrialRun('proj-1'));
    await act(async () => {
      await result.current.start();
    });

    await waitFor(() => {
      expect(result.current.phase.kind).toBe('failed')
    });
    if (result.current.phase.kind === 'failed') {
      expect(result.current.phase.stage).toBe('analysis');
      expect(result.current.phase.reason).toBe('显存不够');
    }
    await act(async () => {
      await result.current.start();
    });

    await waitFor(() => {
      expect(result.current.phase.kind).toBe('done')
    });
    expect(analysisCalls).toBeGreaterThanOrEqual(2);
    // 提交上去的必须是集的真实 ID（episode_id）：取错键时上线的是 [null]，服务端回
    // 「episode_ids 含无效项」——分析阶段没跑过的新用户，看到的第一句就是这个。
    const startCall = rpcMock.mock.calls.find((c) => c[0] === 'analysis.start');
    expect(startCall?.[1]).toMatchObject({ episode_ids: ['ep1'] });
  });
});

describe('useTrialRun：叫停与失败归属', () => {
  it('组件卸载即停：卸载后不再轮询（服务端任务照跑，重进按集状态续）', async () => {
    vi.useFakeTimers();
    try {
      let polls = 0;
      rpcMock.mockImplementation((method: string): Promise<RpcReply> => {
        if (method === 'analysis.episodes') {
          return Promise.resolve({
            episodes: [{ episode_id: 'ep1', episode_number: 1, status: 'pending' }],
          });
        }
        if (method === 'analysis.status') {
          polls += 1;
          return Promise.resolve({ status: 'running', progress: 10 });
        }
        return Promise.resolve(rpcReply(method));
      });
      const { result, unmount } = renderHook(() => useTrialRun('proj-1'));
      act(() => {
        void result.current.start();
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(polls).toBe(1);

      unmount();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2500 * 4);
      });
      expect(polls).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('失败阶段如实归属：规划、导出挂了不报成「分析失败」，重试从失败的那一步接着跑', async () => {
    rpcMock.mockImplementation((method: string): Promise<RpcReply> => {
      if (method === 'narration.plan_variants') {
        return Promise.reject(new Error('规划服务不可用'));
      }
      return Promise.resolve(rpcReply(method));
    });
    const { result } = renderHook(() => useTrialRun('proj-1'));
    await act(async () => {
      await result.current.start();
    });
    expect(result.current.phase).toMatchObject({
      kind: 'failed',
      stage: 'planning',
      reason: '规划服务不可用',
    });

    // 规划恢复、导出任务自己失败：归到导出，分析没有被重跑
    rpcMock.mockImplementation((method: string): Promise<RpcReply> => {
      if (method === 'jobs.get') {
        return Promise.resolve({
          job: { id: 'j-exp', type: 'export', ref_id: null, status: 'failed', progress: 30 },
        });
      }
      return Promise.resolve(rpcReply(method));
    });
    await act(async () => {
      await result.current.start();
    });
    expect(result.current.phase).toMatchObject({ kind: 'failed', stage: 'export' });
    expect(rpcMock.mock.calls.some((c) => c[0] === 'analysis.start')).toBe(false);
  });

  it('收起之后旧编排不再回写：在途的轮询应答不许把界面又拉回「分析中」', async () => {
    let release: (reply: RpcReply) => void = () => undefined;
    rpcMock.mockImplementation((method: string): Promise<RpcReply> => {
      if (method === 'analysis.episodes') {
        return Promise.resolve({
          episodes: [{ episode_id: 'ep1', episode_number: 1, status: 'pending' }],
        });
      }
      if (method === 'analysis.status') {
        return new Promise<RpcReply>((resolve) => {
          release = resolve; // 取数挂在途，等测试放行——模拟「用户在等结果时点了收起」
        });
      }
      return Promise.resolve(rpcReply(method));
    });
    const { result } = renderHook(() => useTrialRun('proj-1'));
    let run: Promise<void> = Promise.resolve();
    act(() => {
      run = result.current.start();
    });
    await waitFor(() => {
      expect(rpcMock.mock.calls.some((c) => c[0] === 'analysis.status')).toBe(true);
    });

    act(() => {
      result.current.reset();
    });
    expect(result.current.phase.kind).toBe('idle');

    await act(async () => {
      release({ status: 'completed', progress: 100 });
      await run;
    });
    expect(result.current.phase.kind).toBe('idle');
  });
});
