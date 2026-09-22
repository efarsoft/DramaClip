// @vitest-environment jsdom
/**
 * 出片第二步「渲染」：export.submit 把勾选的方案排队成片。
 *
 * 拆分之导出片不再是「一次调用出一部片」，而是「方案 → 导出记录 → 任务」三跳；
 * 被拒的方案逐条带理由（规格 4.4）。这两条用例钉的是：全部终态之前不许提前刷新，
 * 以及逐条拒绝不许演成「什么都没发生」。
 */
import { App as AntdApp } from 'antd';
import { renderHook, act, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { useExportQueue } from '../useExportQueue';

const submit = vi.hoisted(() => vi.fn());
const list = vi.hoisted(() => vi.fn());
const cancel = vi.hoisted(() => vi.fn());

vi.mock('../../../services/client', () => ({
  exportApi: {
    submit: (planIds: string[]): unknown => submit(planIds),
    list: (projectId: string): unknown => list(projectId),
  },
  jobsApi: {
    cancel: (jobId: string): unknown => cancel(jobId),
  },
}));

function wrapper({ children }: { children: ReactNode }): ReactNode {
  return <AntdApp>{children}</AntdApp>;
}

afterEach(() => {
  submit.mockReset();
  list.mockReset();
  cancel.mockReset();
});

it('全部导出跑到终态才刷新出片记录', async () => {
  submit.mockResolvedValue({
    exports: [{ plan_id: 'plan-1', export_id: 'x-1', job_id: 'j-1' }],
    rejected: [],
  });
  list
    .mockResolvedValueOnce([{ id: 'x-1', status: 'running', progress: 30 }])
    .mockResolvedValueOnce([{ id: 'x-1', status: 'completed', progress: 100 }]);
  const onDone = vi.fn();

  const { result } = renderHook(() => useExportQueue('p1', onDone), { wrapper });
  await act(async () => {
    await result.current.run(['plan-1']);
  });

  expect(submit).toHaveBeenCalledWith(['plan-1']);
  await waitFor(() => {
    expect(onDone).toHaveBeenCalledTimes(1);
  });
  expect(result.current.running).toBe(false);
  expect(result.current.percent).toBe(100);
});

it('逐条被拒时把原因留在界面上，不谎报成已提交', async () => {
  submit.mockResolvedValue({
    exports: [],
    rejected: [{ plan_id: 'plan-9', reason: '该方案没有可渲染的解说文案' }],
  });
  const onDone = vi.fn();

  const { result } = renderHook(() => useExportQueue('p1', onDone), { wrapper });
  await act(async () => {
    await result.current.run(['plan-9']);
  });

  expect(result.current.rejected).toEqual([{ plan_id: 'plan-9', reason: '该方案没有可渲染的解说文案' }]);
  expect(onDone).not.toHaveBeenCalled();
  expect(list).not.toHaveBeenCalled();
  expect(result.current.running).toBe(false);
});

it('取消出片不当失败', async () => {
  submit.mockResolvedValue({
    exports: [{ plan_id: 'plan-1', export_id: 'x-1', job_id: 'j-1' }],
    rejected: [],
  });
  list
    .mockResolvedValueOnce([{ id: 'x-1', status: 'pending', progress: 10 }])
    .mockResolvedValueOnce([{ id: 'x-1', status: 'cancelled', progress: 10 }]);
  const onDone = vi.fn();

  const { result } = renderHook(() => useExportQueue('p1', onDone), { wrapper });
  await act(async () => {
    await result.current.run(['plan-1']);
  });

  expect(result.current.error).toBe('');
  expect(onDone).toHaveBeenCalledTimes(1);
  expect(result.current.running).toBe(false);
});

it('轮询再也查不到这批导出时说出来，不许永远转圈', async () => {
  submit.mockResolvedValue({
    exports: [{ plan_id: 'plan-1', export_id: 'x-1', job_id: 'j-1' }],
    rejected: [],
  });
  list.mockResolvedValue([]);
  const onDone = vi.fn();

  const { result } = renderHook(() => useExportQueue('p1', onDone), { wrapper });
  await act(async () => {
    await result.current.run(['plan-1']);
  });

  expect(result.current.error).toContain('x-1');
  expect(onDone).not.toHaveBeenCalled();
  expect(result.current.running).toBe(false);
});
