// @vitest-environment jsdom
/**
 * 出片第一步「规划」：调 narration.plan_variants 产出一组方案，按批次取回。
 *
 * 这条链路曾经直接调 `narration.produce`（一个已在 b20ccba 拆掉的方法），点「开始出片」
 * 必然被 IPC 白名单拒成「未知 RPC 方法」。用例钉住的是：走拆分后的真方法、
 * 只认本次批次、失败必须把原因说出来而不是演成空列表。
 */
import { App as AntdApp } from 'antd';
import { renderHook, act } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import type { NarrationPlan } from '@dramaclip/protocol';
import { usePlanBatch } from '../usePlanBatch';

const planVariants = vi.hoisted(() => vi.fn());
const listPlans = vi.hoisted(() => vi.fn());
const status = vi.hoisted(() => vi.fn());

vi.mock('../../../services/client', () => ({
  narrationApi: {
    planVariants: (projectId: string, modes: string[], k: number): unknown =>
      planVariants(projectId, modes, k),
    listPlans: (projectId: string, batchId?: string): unknown => listPlans(projectId, batchId),
  },
  analysisApi: { status: (jobId: string): unknown => status(jobId) },
  jobsApi: { cancel: (): unknown => Promise.resolve({ cancelling: true }) },
}));

const PLAN: NarrationPlan = {
  id: 'plan-1',
  project_id: 'p1',
  narration_mode: 'full_narration',
  episode_ids: ['e1'],
  plan_data: { timeline: [], narration_texts: [] } as unknown as NarrationPlan['plan_data'],
  status: 'draft',
  created_at: 1,
  angle: '弃婚逆袭',
  batch_id: 'job-1',
};

function wrapper({ children }: { children: ReactNode }): ReactNode {
  return <AntdApp>{children}</AntdApp>;
}

afterEach(() => {
  planVariants.mockReset();
  listPlans.mockReset();
  status.mockReset();
});

it('规划走 narration.plan_variants，并按本次批次取回方案', async () => {
  planVariants.mockResolvedValue({ job_id: 'job-1', k: 3, batch_id: 'job-1' });
  status.mockResolvedValue({ status: 'completed', progress: 100, message: '完成' });
  listPlans.mockResolvedValue([PLAN]);

  const { result } = renderHook(() => usePlanBatch('p1'), { wrapper });
  await act(async () => {
    await result.current.run(['full_narration'], 3);
  });

  expect(planVariants).toHaveBeenCalledWith('p1', ['full_narration'], 3);
  expect(listPlans).toHaveBeenCalledWith('p1', 'job-1');
  expect(result.current.plans).toEqual([PLAN]);
  expect(result.current.planning).toBe(false);
});

it('作业失败时说出原因，同时取回已落库的部分方案（规划队列逐条点亮）', async () => {
  planVariants.mockResolvedValue({ job_id: 'job-1', k: 3, batch_id: 'job-1' });
  status.mockResolvedValue({
    status: 'failed',
    progress: 40,
    message: '',
    error: '编剧模型未配置',
  });

  const { result } = renderHook(() => usePlanBatch('p1'), { wrapper });
  await act(async () => {
    await result.current.run(['full_narration'], 3);
  });

  expect(result.current.error).toBe('编剧模型未配置');
  expect(listPlans, '失败也要取回已落库的部分').toHaveBeenCalledWith('p1', 'job-1');
  expect(result.current.failDetail).toBe('编剧模型未配置');
});

it('作业被取消时不把取消演成失败，已落库部分照常取回', async () => {
  planVariants.mockResolvedValue({ job_id: 'job-1', k: 3, batch_id: 'job-1' });
  status.mockResolvedValue({ status: 'cancelled', progress: 40, message: '' });

  const { result } = renderHook(() => usePlanBatch('p1'), { wrapper });
  await act(async () => {
    await result.current.run(['full_narration'], 3);
  });

  expect(result.current.error).toBe('');
  expect(listPlans).toHaveBeenCalledWith('p1', 'job-1');
});
