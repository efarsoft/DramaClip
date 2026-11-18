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

export function useTrialRun(projectId: string): {
  phase: TrialPhase;
  start: () => Promise<void>;
  reset: () => void;
} {
  const [phase, setPhase] = useState<TrialPhase>({ kind: 'idle' });
  const stoppedRef = useRef(false);

  const reset = useCallback((): void => {
    stoppedRef.current = true;
    setPhase({ kind: 'idle' });
  }, []);

  const start = useCallback(async (): Promise<void> => {
    stoppedRef.current = false;
    setPhase({ kind: 'checking' });
    try {
      const { episodes } = await analysisApi.episodes(projectId);
      if (stoppedRef.current) return;
      const summaries = (episodes as unknown as EpisodeSummary[]).slice();
      if (summaries.length === 0) {
        setPhase({ kind: 'no-material' });
        return;
      }
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
        for (;;) {
          if (stoppedRef.current) return;
          const job = await analysisApi.status(job_id);
          setPhase({
            kind: 'analyzing',
            percent: Math.round(job.progress),
            message: job.message ?? '',
          });
          if (job.status === 'completed') break;
          if (job.status !== 'running' && job.status !== 'pending') {
            setPhase({
              kind: 'failed',
              stage: 'analysis',
              reason: job.error || job.message || `分析任务${job.status}`,
            });
            return;
          }
          await sleep(POLL_INTERVAL_MS);
        }
      }

      // ② 规划：纯原片剪辑 ×1 条（零文案模式，全链不触 LLM）
      if (stoppedRef.current) return;
      setPhase({ kind: 'planning', percent: 0, message: '挑选高冲突片段' });
      const planned = await narrationApi.planVariants(projectId, ['raw_clip'], 1);
      for (;;) {
        if (stoppedRef.current) return;
        const job = await analysisApi.status(planned.job_id);
        setPhase({
          kind: 'planning',
          percent: Math.round(job.progress),
          message: job.message ?? '',
        });
        if (job.status === 'completed') break;
        if (job.status !== 'running' && job.status !== 'pending') {
          setPhase({
            kind: 'failed',
            stage: 'planning',
            reason: job.error || job.message || `规划任务${job.status}`,
          });
          return;
        }
        await sleep(POLL_INTERVAL_MS);
      }
      const batchPlans = await narrationApi.listPlans(projectId, planned.batch_id);
      const planId = batchPlans[0]?.id;
      if (planId === undefined) {
        setPhase({ kind: 'failed', stage: 'planning', reason: '规划完成但没有产出方案' });
        return;
      }

      // ③ 导出：提交后按导出任务轮询到终态
      if (stoppedRef.current) return;
      setPhase({ kind: 'exporting', percent: 0, message: '合成成片' });
      const submission = await exportApi.submit([planId]);
      if (submission.exports.length === 0) {
        setPhase({
          kind: 'failed',
          stage: 'export',
          reason: submission.rejected[0]?.reason ?? '导出被拒',
        });
        return;
      }
      const submitted = submission.exports[0];
      if (submitted === undefined) {
        setPhase({ kind: 'failed', stage: 'export', reason: '导出提交返回为空' });
        return;
      }
      const { export_id, job_id } = submitted;
      for (;;) {
        if (stoppedRef.current) return;
        const { job } = await jobsApi.get(job_id);
        setPhase({
          kind: 'exporting',
          percent: Math.round(job.progress ?? 0),
          message: '',
        });
        if (job.status === 'completed') {
          setPhase({ kind: 'done', exportId: export_id });
          return;
        }
        if (job.status !== 'running' && job.status !== 'pending') {
          setPhase({
            kind: 'failed',
            stage: 'export',
            reason: job.error || `导出任务${job.status}`,
          });
          return;
        }
        await sleep(POLL_INTERVAL_MS);
      }
    } catch (exc) {
      if (stoppedRef.current) return;
      setPhase({
        kind: 'failed',
        stage: 'analysis',
        reason: exc instanceof Error ? exc.message : String(exc),
      });
    }
  }, [projectId]);

  return { phase, start, reset };
}
