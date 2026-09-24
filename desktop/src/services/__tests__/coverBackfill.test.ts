/** 封面补拍涓流纪律：有进展才续轮、无进展/失败即停、取消器掐定时器与迟到回调。 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { scheduleCoverBackfill, type CoverBackfillResult } from '../coverBackfill';

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

async function flush(): Promise<void> {
  await vi.advanceTimersByTimeAsync(0);
}

describe('scheduleCoverBackfill 续轮纪律', () => {
  it('无欠账：只拍一轮，不空转', async () => {
    const call = vi.fn<() => Promise<CoverBackfillResult>>();
    call.mockResolvedValue({ generated: 0 });
    const onProgress = vi.fn();
    scheduleCoverBackfill(call, onProgress);
    await flush();
    expect(call).toHaveBeenCalledTimes(1);
    expect(onProgress).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(call).toHaveBeenCalledTimes(1);
  });

  it('有欠账且有进展：续轮涓流；一旦无进展即停（死路径不配无限重试）', async () => {
    const call = vi.fn<() => Promise<CoverBackfillResult>>();
    call
      .mockResolvedValueOnce({ generated: 2, remaining: 3 })
      .mockResolvedValueOnce({ generated: 0, remaining: 3 });
    const onProgress = vi.fn();
    scheduleCoverBackfill(call, onProgress, { delayMs: 1500 });
    await flush();
    expect(onProgress).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1500);
    expect(call).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(call, '无进展还续轮就是陪服务端空转').toHaveBeenCalledTimes(2);
  });

  it('旧服务无 remaining 字段：视同无欠账，不续轮', async () => {
    const call = vi.fn<() => Promise<CoverBackfillResult>>();
    call.mockResolvedValue({ generated: 5 });
    scheduleCoverBackfill(call, vi.fn());
    await vi.advanceTimersByTimeAsync(10_000);
    expect(call).toHaveBeenCalledTimes(1);
  });
});

describe('scheduleCoverBackfill 停止纪律', () => {

  it('取消：定时器掐掉，迟到回调不再触发 onProgress', async () => {
    const call = vi.fn<() => Promise<CoverBackfillResult>>();
    call.mockResolvedValue({ generated: 1, remaining: 2 });
    const onProgress = vi.fn();
    const cancel = scheduleCoverBackfill(call, onProgress);
    cancel();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(call).toHaveBeenCalledTimes(1);
    expect(onProgress).not.toHaveBeenCalled();
  });

  it('失败：说一次现象即止，不重试', async () => {
    const call = vi.fn<() => Promise<CoverBackfillResult>>();
    call.mockRejectedValue(new Error('管道断开'));
    const onFailure = vi.fn();
    scheduleCoverBackfill(call, vi.fn(), { onFailure });
    await flush();
    expect(onFailure).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(call).toHaveBeenCalledTimes(1);
  });

  it('maxRounds 封顶：服务端账目异常永远报进展也不陪跑无穷', async () => {
    const call = vi.fn<() => Promise<CoverBackfillResult>>();
    call.mockResolvedValue({ generated: 1, remaining: 9 });
    scheduleCoverBackfill(call, vi.fn(), { maxRounds: 3, delayMs: 100 });
    await vi.advanceTimersByTimeAsync(10_000);
    expect(call).toHaveBeenCalledTimes(3);
  });
});
