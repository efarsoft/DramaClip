// @vitest-environment jsdom
/** 一键串装链的状态机钉（业主拍板推荐档=Paraformer-large，2026-11-16）：
 *  环境→三包逐下（串行闸）→完成回调；断点自愈（动手前先查现状）、失败进 error
 *  且重试从断点续走、取消回 idle 不留进行态假象。 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useOnboardingChain } from '../useOnboardingChain';
import { RECOMMENDED_CHAIN } from '../onboardingModel';

const status = vi.hoisted(() => vi.fn());
const installRuntime = vi.hoisted(() => vi.fn());
const jobGet = vi.hoisted(() => vi.fn());
const jobList = vi.hoisted(() => vi.fn());
const jobCancel = vi.hoisted(() => vi.fn());
const download = vi.hoisted(() => vi.fn());
const list = vi.hoisted(() => vi.fn());

vi.mock('../../../services/client', () => ({
  localRuntimeApi: {
    status: (...a: unknown[]): unknown => status(...a),
    install: (...a: unknown[]): unknown => installRuntime(...a),
  },
  jobsApi: {
    get: (...a: unknown[]): unknown => jobGet(...a),
    list: (...a: unknown[]): unknown => jobList(...a),
    cancel: (...a: unknown[]): unknown => jobCancel(...a),
  },
  modelsApi: {
    download: (modelId: string, source?: string): unknown => download(modelId, source),
    list: (...a: unknown[]): unknown => list(...a),
  },
}));

/** 测试态账本：download 发起即视为装好——链的裁定全走 models.list（与真实
 *  服务端「终态后查列表」同一口径），不依赖进度事件。 */
const installedIds = new Set<string>();
const ALL_IDS = [...RECOMMENDED_CHAIN, 'faster-whisper-small'];

function asrRows(): unknown[] {
  return ALL_IDS.map((model_id) => ({
    model_id,
    kind: 'asr',
    name: model_id,
    status: installedIds.has(model_id) ? 'installed' : 'not_installed',
  }));
}

beforeEach(() => {
  vi.useFakeTimers();
  installedIds.clear();
  status.mockReset();
  installRuntime.mockReset();
  jobGet.mockReset();
  jobList.mockReset();
  jobCancel.mockReset();
  download.mockReset();
  list.mockReset();
  list.mockImplementation(() => Promise.resolve(asrRows()));
  jobList.mockResolvedValue({ jobs: [] });
  download.mockImplementation((modelId: string) => {
    installedIds.add(modelId);
    return Promise.resolve({ job_id: 'd1' });
  });
});

afterEach(() => {
  vi.useRealTimers();
});

/** 推进假时钟直到条件成立（每轮一拍 3s 轮询窗），超轮数抛错防死循环。 */
async function driveUntil(
  result: { current: { phase: { kind: string } } },
  cond: () => boolean,
  maxTicks = 40,
): Promise<void> {
  for (let i = 0; i < maxTicks; i += 1) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_000);
    });
    if (cond()) return;
  }
  throw new Error(`链未在 ${String(maxTicks)} 轮内到位：phase=${result.current.phase.kind}`);
}

it('全链 happy path：缺环境→装→三包逐下（串行顺序）→done+回调一次', async () => {
  status.mockResolvedValue({ installed: false, groups: {} });
  installRuntime.mockResolvedValue({ job_id: 'rt1' });
  jobGet.mockResolvedValueOnce({ job: { status: 'running', progress: 30, label: '下载 torch' } }).mockResolvedValue({
    job: { status: 'completed', progress: 100, label: '' },
  });
  const onChanged = vi.fn();
  const { result } = renderHook(() => useOnboardingChain(onChanged));
  act(() => {
    result.current.startRecommended();
  });
  await driveUntil(result, () => result.current.phase.kind === 'done');
  expect(installRuntime).toHaveBeenCalledTimes(1);
  expect(download.mock.calls.map((c: unknown[]) => c[0])).toEqual(RECOMMENDED_CHAIN);
  expect(result.current.phase.kind).toBe('done');
  expect(onChanged).toHaveBeenCalledTimes(1);
});

it('环境已就绪：跳过 install 直接逐包', async () => {
  status.mockResolvedValue({ installed: true, groups: { torch: true, funasr: true } });
  const onChanged = vi.fn();
  const { result } = renderHook(() => useOnboardingChain(onChanged));
  act(() => {
    result.current.startRecommended();
  });
  await driveUntil(result, () => result.current.phase.kind === 'done');
  expect(installRuntime).not.toHaveBeenCalled();
  expect(download.mock.calls.map((c: unknown[]) => c[0])).toEqual(RECOMMENDED_CHAIN);
});

it('断点自愈：链首包已装，只下剩余两包', async () => {
  status.mockResolvedValue({ installed: true, groups: { torch: true, funasr: true } });
  installedIds.add('paraformer-large');
  const onChanged = vi.fn();
  const { result } = renderHook(() => useOnboardingChain(onChanged));
  act(() => {
    result.current.startRecommended();
  });
  await driveUntil(result, () => result.current.phase.kind === 'done');
  expect(download.mock.calls.map((c: unknown[]) => c[0])).toEqual(['fsmn-vad', 'campplus-sv']);
});

it('环境装失败：error 带原话；重试换 completed 后从断点走到 done', async () => {
  status.mockResolvedValue({ installed: false, groups: {} });
  installRuntime.mockResolvedValue({ job_id: 'rt1' });
  jobGet.mockResolvedValue({ job: { status: 'failed', progress: 10, label: '', error: '磁盘空间不足' } });
  const onChanged = vi.fn();
  const { result } = renderHook(() => useOnboardingChain(onChanged));
  act(() => {
    result.current.startRecommended();
  });
  await driveUntil(result, () => result.current.phase.kind === 'error');
  const failedPhase = result.current.phase;
  if (failedPhase.kind !== 'error') throw new Error('unreachable: driveUntil 已保证 error 态');
  expect(failedPhase.problem).toContain('磁盘空间不足');
  expect(download).not.toHaveBeenCalled();

  // 重试：环境 job 改判 completed，断点续走到 done
  jobGet.mockResolvedValue({ job: { status: 'completed', progress: 100, label: '' } });
  act(() => {
    result.current.startRecommended();
  });
  await driveUntil(result, () => result.current.phase.kind === 'done');
  expect(download.mock.calls.map((c: unknown[]) => c[0])).toEqual(RECOMMENDED_CHAIN);
  expect(onChanged).toHaveBeenCalledTimes(1);
});

it('快速档：免环境单包直下', async () => {
  const onChanged = vi.fn();
  const { result } = renderHook(() => useOnboardingChain(onChanged));
  act(() => {
    result.current.startQuick('faster-whisper-small', 'Whisper Small');
  });
  await driveUntil(result, () => result.current.phase.kind === 'done');
  expect(status).not.toHaveBeenCalled();
  expect(installRuntime).not.toHaveBeenCalled();
  expect(download.mock.calls.map((c: unknown[]) => c[0])).toEqual(['faster-whisper-small']);
  expect(onChanged).toHaveBeenCalledTimes(1);
});

it('取消：链回 idle，不把界面留在进行态', async () => {
  status.mockResolvedValue({ installed: true, groups: { torch: true, funasr: true } });
  // 包下载中：list 恒报在跑（等不到终态），制造「卡在下载阶段」的场景
  jobList.mockResolvedValue({
    jobs: [{ id: 'j1', type: 'model_download', ref_id: 'paraformer-large' }],
  });
  const onChanged = vi.fn();
  const { result } = renderHook(() => useOnboardingChain(onChanged));
  act(() => {
    result.current.startRecommended();
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3_000);
  });
  expect(result.current.phase.kind).toBe('download');
  act(() => {
    result.current.cancel();
  });
  await driveUntil(result, () => result.current.phase.kind === 'idle');
  expect(result.current.phase.kind).toBe('idle');
  expect(onChanged).not.toHaveBeenCalled();
});

it('全装完再发起：三包全跳过，直接 done（防手滑重下）', async () => {
  status.mockResolvedValue({ installed: true, groups: { torch: true, funasr: true } });
  for (const id of ALL_IDS) installedIds.add(id);
  const onChanged = vi.fn();
  const { result } = renderHook(() => useOnboardingChain(onChanged));
  act(() => {
    result.current.startRecommended();
  });
  await driveUntil(result, () => result.current.phase.kind === 'done');
  expect(download).not.toHaveBeenCalled();
  expect(onChanged).toHaveBeenCalledTimes(1);
});

it('环境「已就绪」竞态拒绝：error 原话可见；重试时判据翻齐即自愈', async () => {
  status.mockResolvedValue({ installed: false, groups: {} }); // 前端判缺 → 发 install
  installRuntime.mockRejectedValue(new Error('[-32500] 本地智能运行环境已就绪，无需重复安装'));
  const onChanged = vi.fn();
  const { result } = renderHook(() => useOnboardingChain(onChanged));
  act(() => {
    result.current.startRecommended();
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  await driveUntil(result, () => result.current.phase.kind === 'error');
  const racePhase = result.current.phase;
  if (racePhase.kind !== 'error') throw new Error('unreachable: driveUntil 已保证 error 态');
  expect(racePhase.problem).toContain('已就绪');
  expect(download).not.toHaveBeenCalled();

  // 重试：status 判据翻齐（竞态窗口已过）→ 跳过环境，三包走完
  status.mockResolvedValue({ installed: true, groups: { torch: true, funasr: true } });
  act(() => {
    result.current.startRecommended();
  });
  await driveUntil(result, () => result.current.phase.kind === 'done');
  expect(download.mock.calls.map((c: unknown[]) => c[0])).toEqual(RECOMMENDED_CHAIN);
  expect(onChanged).toHaveBeenCalledTimes(1);
});
