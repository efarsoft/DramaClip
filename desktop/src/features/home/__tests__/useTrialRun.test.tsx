/** 零配置试跑编排钉：免文案链（分析跳过→规划→导出）状态机与断点语义。 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useTrialRun } from '../useTrialRun';

const rpcMock = vi.fn();
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

function rpcReply(method: string): unknown {
  switch (method) {
    case 'analysis.episodes':
      return { episodes: [{ id: 'ep2', episode_number: 2, status: 'done' }, { id: 'ep1', episode_number: 1, status: 'done' }] };
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
    await waitFor(() => expect(result.current.phase.kind).toBe('done'));
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
    await waitFor(() => expect(result.current.phase.kind).toBe('no-material'));
    expect(rpcMock.mock.calls.some((c) => c[0] === 'narration.plan_variants')).toBe(false);
  });

  it('分析失败：failed 带阶段与原因，重试从失败阶段重入', async () => {
    let analysisCalls = 0;
    rpcMock.mockImplementation((method: string) => {
      if (method === 'analysis.episodes') {
        return Promise.resolve({
          episodes: [{ id: 'ep1', episode_number: 1, status: 'pending' }],
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
    await waitFor(() => expect(result.current.phase.kind).toBe('failed'));
    if (result.current.phase.kind === 'failed') {
      expect(result.current.phase.stage).toBe('analysis');
      expect(result.current.phase.reason).toBe('显存不够');
    }
    await act(async () => {
      await result.current.start();
    });
    await waitFor(() => expect(result.current.phase.kind).toBe('done'));
    expect(analysisCalls).toBeGreaterThanOrEqual(2);
  });
});
