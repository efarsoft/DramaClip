/** 零配置试跑（2026-11-18 立项）：一键把「第一集 → 纯原片剪辑 → 出片」跑完。
 *
 * 目标（验收标尺「10 分钟内看到第一条成片」）：新用户装完识别模型、导入素材后，
 * 不配文案 LLM 也能出第一条片——全链只走免文案模式（raw_clip），编排是前端对
 * 既有 RPC 的按序驱动（analysis.start → narration.plan_variants → export.submit，
 * 逐段轮询到终态），零后端改动。断点语义：重试从失败阶段重入，已完成的分析按
 * 集状态天然跳过；组件卸载即停（内存编排，服务端任务继续跑，重进按集状态续）。
 */
import { useCallback, useRef, useState } from 'react';
import { analysisApi, exportApi, jobsApi, narrationApi } from '../../services/client';

const POLL_INTERVAL_MS = 2500;

export type TrialPhase =
  | { readonly kind: 'idle' }
  | { readonly kind: 'checking' }
  | { readonly kind: 'no-material' }
  | { readonly kind: 'analyzing'; readonly percent: number; readonly message: string }
  | { readonly kind: 'planning'; readonly percent: number; readonly message: string }
  | { readonly kind: 'exporting'; readonly percent: number; readonly message: string }
  | { readonly kind: 'done'; readonly exportId: string }
  | {
      readonly kind: 'failed';
      readonly stage: 'analysis' | 'planning' | 'export';
      readonly reason: string;
    };

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

interface EpisodeSummary {
  readonly id: string;
  readonly episode_number: number;
  readonly status: string;
}

/** 通用轮询：status 取数 → 进度回写 → 终态裁决（completed 放行 / 其余按失败带原因）。 */
async function pollUntilDone(
  fetch: () => Promise<{ status: string; progress: number; message?: string; error?: string | null }>,
  onTick: (percent: number, message: string) => void,
  isStopped: () => boolean,
  failReason: (job: { status: string; error?: string | null; message?: string }) => string,
): Promise<void> {
  for (;;) {
    if (isStopped()) return;
    const job = await fetch();
    onTick(Math.round(job.progress), job.message ?? '');
    if (job.status === 'completed') return;
    if (job.status !== 'running' && job.status !== 'pending') {
      throw new Error(failReason(job));
    }
    await sleep(POLL_INTERVAL_MS);
  }
}

export function useTrialRun(
  projectId: string,
): {
  phase: TrialPhase;
  start: () => Promise<void>;
  reset: () => void;
} {
  const [phase, setPhase] = useState<TrialPhase>({ kind: 'idle' });
  const stoppedRef = useRef(false);
  // 经函数读取打断控制流窄化（直接读 ref.current 会被判「always falsy」）
  const stopped = (): boolean => stoppedRef.current;

  const reset = useCallback((): void => {
    stoppedRef.current = true;
    setPhase({ kind: 'idle' });
  }, []);

  const start = useCallback(async (): Promise<void> => {
    stoppedRef.current = false;
    setPhase({ kind: 'checking' });
    try {
      const { episodes } = await analysisApi.episodes(projectId);
      if (stopped()) return;
      const summaries = (episodes as unknown as EpisodeSummary[]).slice();
      const sorted = summaries.slice().sort((a, b) => a.episode_number - b.episode_number);
      const first = sorted[0];
      if (first === undefined) {
        setPhase({ kind: 'no-material' });
        return;
      }

      // ① 分析：目标集未完成才提交（done 天然跳过——重试/重入免重跑）
      if (first.status !== 'done') {
        setPhase({ kind: 'analyzing', percent: 0, message: '准备分析' });
        const { job_id } = await analysisApi.start(projectId, [first.id]);
        await pollUntilDone(
          () => analysisApi.status(job_id),
          (percent, message) => {
            setPhase({ kind: 'analyzing', percent, message });
          },
          () => stopped(),
          (job) => job.error ?? job.message ?? `分析任务${job.status}`,
        );
        if (stopped()) return;
      }

      // ② 规划：纯原片剪辑 ×1 条（零文案模式，全链不触 LLM）
      setPhase({ kind: 'planning', percent: 0, message: '挑选高冲突片段' });
      const planned = await narrationApi.planVariants(projectId, ['raw_clip'], 1);
      await pollUntilDone(
        () => analysisApi.status(planned.job_id),
        (percent, message) => {
          setPhase({ kind: 'planning', percent, message });
        },
        () => stoppedRef.current,
        (job) => job.error ?? job.message ?? `规划任务${job.status}`,
      );
      if (stopped()) return;
      const batchPlans = await narrationApi.listPlans(projectId, planned.batch_id);
      const planId = batchPlans[0]?.id;
      if (planId === undefined) {
        setPhase({ kind: 'failed', stage: 'planning', reason: '规划完成但没有产出方案' });
        return;
      }

      // ③ 导出：提交后按导出任务轮询到终态
      setPhase({ kind: 'exporting', percent: 0, message: '合成成片' });
      const submission = await exportApi.submit([planId]);
      const submitted = submission.exports[0];
      if (submitted === undefined) {
        setPhase({
          kind: 'failed',
          stage: 'export',
          reason: submission.rejected[0]?.reason ?? '导出被拒',
        });
        return;
      }
      await pollUntilDone(
        () => jobsApi.get(submitted.job_id).then(({ job }) => job),
        (percent, message) => {
          setPhase({ kind: 'exporting', percent, message });
        },
        () => stoppedRef.current,
        (job) => job.error ?? `导出任务${job.status}`,
      );
      if (stopped()) return;
      setPhase({ kind: 'done', exportId: submitted.export_id });
    } catch (exc) {
      if (stopped()) return;
      setPhase({
        kind: 'failed',
        stage: 'analysis',
        reason: exc instanceof Error ? exc.message : String(exc),
      });
    }
  }, [projectId]);

  return { phase, start, reset };
}
