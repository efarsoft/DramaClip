// @vitest-environment jsdom
/**
 * 出片提交侧（卷三图4）：submit 后**展开任务抽屉**看真进度，不原地假装进度；
 * 守望任务快照，这批全部终态才刷新出片记录；被拒与失败原文照旧上屏。
 */
import { renderHook, act, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { JobInfo } from '@dramaclip/protocol';
import { useJobsStore } from '../../../stores/jobs';
import { useExportQueue } from '../useExportQueue';

const submit = vi.hoisted(() => vi.fn());

vi.mock('../../../services/client', () => ({
  exportApi: {
    submit: (planIds: string[]): unknown => submit(planIds),
  },
}));

function job(id: string, status: JobInfo['status'], error?: string): JobInfo {
  return {
    id,
    type: 'export',
    ref_id: 'x-1',
    status,
    progress: status === 'completed' ? 100 : 30,
    error,
    created_at: 0,
    updated_at: 0,
  };
}

function feed(jobs: JobInfo[]): void {
  act(() => {
    useJobsStore.getState().setSnapshot(jobs, 1000);
  });
}

beforeEach(() => {
  useJobsStore.setState({ jobs: [], available: true, drawerOpen: false });
});

afterEach(() => {
  submit.mockReset();
});

it('提交成功即展开任务抽屉；快照里全部终态才刷新出片记录', async () => {
  submit.mockResolvedValue({
    exports: [{ plan_id: 'plan-1', export_id: 'x-1', job_id: 'j-1' }],
    rejected: [],
  });
  const onDone = vi.fn();
  const { result } = renderHook(() => useExportQueue(onDone));

  await act(async () => {
    await result.current.run(['plan-1']);
  });
  expect(submit).toHaveBeenCalledWith(['plan-1']);
  expect(useJobsStore.getState().drawerOpen).toBe(true);
  expect(onDone).not.toHaveBeenCalled();

  // 还在跑：不许提前刷新（旧钉法保留——只是进度改由抽屉的真快照呈现）
  feed([job('j-1', 'running')]);
  expect(onDone).not.toHaveBeenCalled();

  feed([job('j-1', 'completed')]);
  await waitFor(() => {
    expect(onDone).toHaveBeenCalledTimes(1);
  });
  expect(result.current.error).toBe('');
});

it('快照还没见到这批作业时不动：取不到 ≠ 已完成', async () => {
  submit.mockResolvedValue({
    exports: [{ plan_id: 'plan-1', export_id: 'x-1', job_id: 'j-1' }],
    rejected: [],
  });
  const onDone = vi.fn();
  const { result } = renderHook(() => useExportQueue(onDone));
  await act(async () => {
    await result.current.run(['plan-1']);
  });
  // 快照里只有别的作业：这批还没进来，不刷新
  feed([job('j-other', 'completed')]);
  expect(onDone).not.toHaveBeenCalled();
});

it('逐条被拒时原因留在界面上，不谎报已提交、不开抽屉', async () => {
  submit.mockResolvedValue({
    exports: [],
    rejected: [{ plan_id: 'plan-9', reason: '该方案没有可渲染的解说文案' }],
  });
  const onDone = vi.fn();
  const { result } = renderHook(() => useExportQueue(onDone));
  await act(async () => {
    await result.current.run(['plan-9']);
  });
  expect(result.current.rejected).toEqual([{ plan_id: 'plan-9', reason: '该方案没有可渲染的解说文案' }]);
  expect(useJobsStore.getState().drawerOpen).toBe(false);
  expect(onDone).not.toHaveBeenCalled();
});

it('失败终态：原文上屏不截断，且仍然刷新记录', async () => {
  submit.mockResolvedValue({
    exports: [{ plan_id: 'plan-1', export_id: 'x-1', job_id: 'j-1' }],
    rejected: [],
  });
  const onDone = vi.fn();
  const { result } = renderHook(() => useExportQueue(onDone));
  await act(async () => {
    await result.current.run(['plan-1']);
  });
  feed([job('j-1', 'failed', 'ffmpeg 退出码 1：编码器崩溃')]);
  await waitFor(() => {
    expect(onDone).toHaveBeenCalledTimes(1);
  });
  expect(result.current.error).toContain('ffmpeg 退出码 1：编码器崩溃');
});

it('取消终态不当失败', async () => {
  submit.mockResolvedValue({
    exports: [{ plan_id: 'plan-1', export_id: 'x-1', job_id: 'j-1' }],
    rejected: [],
  });
  const onDone = vi.fn();
  const { result } = renderHook(() => useExportQueue(onDone));
  await act(async () => {
    await result.current.run(['plan-1']);
  });
  feed([job('j-1', 'cancelled')]);
  await waitFor(() => {
    expect(onDone).toHaveBeenCalledTimes(1);
  });
  expect(result.current.error).toBe('');
});

it('submit 抛错：错误原文记账，不开抽屉', async () => {
  submit.mockRejectedValue(new Error('管道断开'));
  const onDone = vi.fn();
  const { result } = renderHook(() => useExportQueue(onDone));
  await act(async () => {
    await result.current.run(['plan-1']);
  });
  expect(result.current.error).toBe('管道断开');
  expect(useJobsStore.getState().drawerOpen).toBe(false);
});
