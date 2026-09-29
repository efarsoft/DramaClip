/** 阶段③「规划」：narration.plan_variants 产出本批 K 条方案，轮询作业按批次取回。
 *
 * 轮询期间方案**增量可见**（服务端逐条落库）且失败明细即时透出（jobs.error 由
 * 服务端 append_detail 运行中追加）——「规划队列」靠这两路数据逐行点亮状态，
 * 不再全军沉默到批次结束。
 */
import { useCallback, useRef, useState } from 'react';
import type { NarrationMode, NarrationPlan } from '@dramaclip/protocol';
import { analysisApi, jobsApi, narrationApi } from '../../services/client';
import { POLL_INTERVAL_MS, isTerminal, reasonOr, sleep } from './poll';

export interface PlanBatch {
  planning: boolean;
  percent: number;
  stageText: string;
  /** 本批已成功落库的方案（轮询期间逐条增长）。 */
  plans: NarrationPlan[];
  /** 本批作业的失败明细原文（运行中即追加；终态为权威全文）。 */
  failDetail: string;
  /** 本批作业 id（规划队列按它过滤方案与读失败明细）。 */
  batchId: string | null;
  error: string;
  run: (modes: NarrationMode[], k: number) => Promise<void>;
  cancel: () => Promise<void>;
}

export function usePlanBatch(projectId: string): PlanBatch {
  const [planning, setPlanning] = useState(false);
  const [percent, setPercent] = useState(0);
  const [stageText, setStageText] = useState('');
  const [plans, setPlans] = useState<NarrationPlan[]>([]);
  const [failDetail, setFailDetail] = useState('');
  const [batchId, setBatchId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const jobIdRef = useRef<string | null>(null);

  const cancel = useCallback(async (): Promise<void> => {
    const jobId = jobIdRef.current;
    if (jobId === null) return;
    await jobsApi.cancel(jobId);
  }, []);

  const run = useCallback(
    async (modes: NarrationMode[], k: number): Promise<void> => {
      if (modes.length === 0 || planning) return;
      setPlanning(true);
      setPlans([]);
      setError('');
      setPercent(0);
      setFailDetail('');
      setStageText('提交规划任务');
      try {
        const { job_id: jobId, batch_id: batch } = await narrationApi.planVariants(
          projectId,
          modes,
          k,
        );
        jobIdRef.current = jobId;
        setBatchId(batch);
        for (;;) {
          const job = await analysisApi.status(jobId);
          setPercent(job.progress);
          setStageText(job.message ?? '');
          setFailDetail(job.error ?? '');
          // 方案逐条落库：轮询期就取回，队列行即时点亮「完成」
          setPlans(await narrationApi.listPlans(projectId, batch));
          if (job.status === 'completed') {
            setPlans(await narrationApi.listPlans(projectId, batch));
            return;
          }
          if (job.status === 'cancelled') {
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
        jobIdRef.current = null;
        setPlanning(false);
        setStageText('');
      }
    },
    [planning, projectId],
  );

  return { planning, percent, stageText, plans, failDetail, batchId, error, run, cancel };
}
