/** 重掷单条：同模式 k=1、exclude 掉被掷的那条；新方案落在新批次，**追加**进当前
 * 视图而不是切走——用户正在挑的是这一批，切走等于把他正在挑的方案藏起来。 */
import { useCallback } from 'react';
import type { NarrationPlan } from '@dramaclip/protocol';
import { analysisApi, narrationApi } from '../../services/client';
import { POLL_INTERVAL_MS, isTerminal, reasonOr, sleep } from './poll';

export interface PlanRerollDeps {
  readonly projectId: string;
  readonly planning: boolean;
  readonly jobIdRef: { current: string | null };
  readonly setPlanning: (value: boolean) => void;
  readonly setError: (value: string) => void;
  readonly setFailDetail: (value: string) => void;
  readonly setStageText: (value: string) => void;
  readonly setPlans: (update: (prev: NarrationPlan[]) => NarrationPlan[]) => void;
}

interface RerollOutcome {
  readonly plans: NarrationPlan[];
  readonly failure: string;
}

/** 等独立小批次到终态：取回该批新增方案，失败原因按作业口径落一句。 */
async function awaitReroll(
  jobId: string,
  projectId: string,
  onTick: (message: string, error: string) => void,
): Promise<RerollOutcome> {
  for (;;) {
    const job = await analysisApi.status(jobId);
    onTick(job.message ?? '', job.error ?? '');
    if (isTerminal(job.status)) {
      const all = await narrationApi.listPlans(projectId);
      return {
        plans: all.filter((p) => p.batch_id === jobId),
        failure:
          job.status === 'completed'
            ? ''
            : reasonOr(job.error, reasonOr(job.message, `重掷作业${job.status}`)),
      };
    }
    await sleep(POLL_INTERVAL_MS);
  }
}

export function usePlanReroll(deps: PlanRerollDeps): (plan: NarrationPlan) => Promise<void> {
  const { projectId, planning, jobIdRef, setPlanning, setError, setFailDetail, setStageText, setPlans } =
    deps;
  return useCallback(
    async (plan: NarrationPlan): Promise<void> => {
      if (planning) return;
      setPlanning(true);
      setError('');
      setFailDetail('');
      setStageText('重掷此条');
      try {
        const { job_id: jobId } = await narrationApi.planVariants(
          projectId,
          [plan.narration_mode],
          1,
          [plan.id],
        );
        jobIdRef.current = jobId;
        const outcome = await awaitReroll(jobId, projectId, (message, detail) => {
          setStageText(message);
          setFailDetail(detail);
        });
        setPlans((prev) => {
          const known = new Set(prev.map((p) => p.id));
          const fresh = outcome.plans.filter((p) => !known.has(p.id));
          return fresh.length > 0 ? [...prev, ...fresh] : prev;
        });
        if (outcome.failure !== '') setError(outcome.failure);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        jobIdRef.current = null;
        setPlanning(false);
        setStageText('');
      }
    },
    [planning, projectId, jobIdRef, setPlanning, setError, setFailDetail, setStageText, setPlans],
  );
}
