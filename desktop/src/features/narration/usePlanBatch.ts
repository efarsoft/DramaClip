/** 阶段③「规划」：narration.plan_variants 产出本批 K 条方案，轮询作业后按批次取回。 */
import { useCallback, useState } from 'react';
import type { NarrationMode, NarrationPlan } from '@dramaclip/protocol';
import { analysisApi, narrationApi } from '../../services/client';
import { POLL_INTERVAL_MS, isTerminal, reasonOr, sleep } from './poll';

export interface PlanBatch {
  planning: boolean;
  percent: number;
  stageText: string;
  plans: NarrationPlan[];
  error: string;
  run: (modes: NarrationMode[], k: number) => Promise<void>;
}

export function usePlanBatch(projectId: string): PlanBatch {
  const [planning, setPlanning] = useState(false);
  const [percent, setPercent] = useState(0);
  const [stageText, setStageText] = useState('');
  const [plans, setPlans] = useState<NarrationPlan[]>([]);
  const [error, setError] = useState('');

  const run = useCallback(
    async (modes: NarrationMode[], k: number): Promise<void> => {
      if (modes.length === 0 || planning) return;
      setPlanning(true);
      setPlans([]);
      setError('');
      setPercent(0);
      setStageText('提交规划任务');
      try {
        const { job_id: jobId, batch_id: batchId } = await narrationApi.planVariants(
          projectId,
          modes,
          k,
        );
        for (;;) {
          const job = await analysisApi.status(jobId);
          setPercent(job.progress);
          setStageText(job.message ?? '');
          if (job.status === 'completed') {
            setPlans(await narrationApi.listPlans(projectId, batchId));
            return;
          }
          if (isTerminal(job.status)) {
            setError(reasonOr(job.error, reasonOr(job.message, `规划作业${job.status}`)));
            return;
          }
          await sleep(POLL_INTERVAL_MS);
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        setPlanning(false);
        setStageText('');
      }
    },
    [planning, projectId],
  );

  return { planning, percent, stageText, plans, error, run };
}
