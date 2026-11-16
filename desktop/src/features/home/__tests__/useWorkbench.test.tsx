// @vitest-environment jsdom
/**
 * 工作台取数的重试纪律（装测 2026-11-16 实锤的回归钉）：
 * 就绪瞬间的首查可能一过性失败——一次性取数会把「任务状态取不到」永久钉在
 * 首页。这里钉三件事：失败后按节奏重试到取全、取全即停不空转、重试有界
 * 到点停手（留给「重启服务」入口，不做成无限轮询）。
 */
import { renderHook, cleanup } from '@testing-library/react';
import { act } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useWorkbench } from '../useWorkbench';
import { useUiStore } from '../../../stores/ui';

const projectList = vi.hoisted(() => vi.fn());
const rpc = vi.hoisted(() => vi.fn());
const listWorks = vi.hoisted(() => vi.fn());
const jobsList = vi.hoisted(() => vi.fn());

vi.mock('../../../services/client', () => ({
  projectApi: { list: (): unknown => projectList() },
  rpc: (method: string, params?: Record<string, unknown>): unknown => rpc(method, params),
  listWorks: (limit: number): unknown => listWorks(limit),
  jobsApi: { list: (limit: number, activeOnly?: boolean): unknown => jobsList(limit, activeOnly) },
}));

const FAIL = new Error('服务未就绪');

function mockAllFail(): void {
  projectList.mockRejectedValue(FAIL);
  rpc.mockRejectedValue(FAIL);
  listWorks.mockRejectedValue(FAIL);
  jobsList.mockRejectedValue(FAIL);
}

/** 全绿的一轮：models 非空、settings 有键、jobs 有 server_time。 */
function mockAllOk(): void {
  projectList.mockResolvedValue([]);
  rpc.mockImplementation((method: string) =>
    method === 'models.list'
      ? Promise.resolve([{ id: 'm1', name: 'x', required: true, status: 'installed' }])
      : Promise.resolve({ 'llm.base_url': '', 'tts.engine': 'edge' }),
  );
  listWorks.mockResolvedValue([]);
  jobsList.mockResolvedValue({ jobs: [], server_time_ms: 1_700_000_000_000 });
}

beforeEach(() => {
  vi.useFakeTimers();
  // restoreAllMocks 不清 vi.fn() 调用史，计数断言必须逐个显式清零
  projectList.mockClear();
  rpc.mockClear();
  listWorks.mockClear();
  jobsList.mockClear();
  useUiStore.setState({ serviceState: 'ready' });
});

afterEach(() => {
  cleanup(); // vitest 未开 globals，RTL 自动清理不注册——不卸载会留下订阅共享 store 的僵尸 hook
  vi.useRealTimers();
  vi.restoreAllMocks();
  useUiStore.setState({ serviceState: 'starting' });
});

it('首查全灭后按节奏重试，取全即恢复', async () => {
  mockAllFail();
  const { result } = renderHook(() => useWorkbench());
  // 首轮（全灭）：jobs 停在不可用、models 停在 null
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  expect(result.current.data.jobsAvailable).toBe(false);
  expect(result.current.data.models).toBeNull();

  // 第二轮全绿：五个源都恢复
  mockAllOk();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5_000);
  });
  expect(result.current.data.jobsAvailable).toBe(true);
  expect(result.current.data.models).not.toBeNull();
  expect(result.current.data.llmBaseUrl).toBe('');
});

it('取全即停：不再发多余的一轮', async () => {
  mockAllOk();
  const { result } = renderHook(() => useWorkbench());
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  expect(result.current.data.jobsAvailable).toBe(true);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(60_000);
  });
  expect(jobsList).toHaveBeenCalledTimes(1);
});

it('重试有界：六次到点停手，不做无限轮询', async () => {
  mockAllFail();
  const { result } = renderHook(() => useWorkbench());
  // 首轮 + 6 次重试 = 7 轮；再往前推 5 分钟也不应再多发
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(60_000);
  });
  expect(jobsList).toHaveBeenCalledTimes(7);
  expect(result.current.data.jobsAvailable).toBe(false);
});
