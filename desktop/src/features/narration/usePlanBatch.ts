/** 阶段③「规划」：narration.plan_variants 产出本批 K 条方案，轮询作业按批次取回。
 *
 * 轮询期间方案**增量可见**（服务端逐条落库）且失败明细即时透出（jobs.error 由
 * 服务端 append_detail 运行中追加）——「规划队列」靠这两路数据逐行点亮状态。
 * 页面重进时按项目找回在跑的规划作业并重新挂上轮询：服务端任务在后台继续，
 * 队列不因导航丢失。提交规格（模式×条数）随项目设置持久化（服务端创建批次时
 * 写入 last_plan_batch，重进时从项目详情读回）。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { NarrationMode, NarrationPlan } from '@dramaclip/protocol';
import { analysisApi, jobsApi, narrationApi, projectApi } from '../../services/client';
import { POLL_INTERVAL_MS, isTerminal, reasonOr, sleep } from './poll';

export interface PlanBatchSpec {
  modes: NarrationMode[];
  k: number;
}

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
  /** 提交规格（模式×条数）：在跑时从项目设置恢复，供规划队列画骨架。 */
  spec: PlanBatchSpec | null;
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
  const [spec, setSpec] = useState<PlanBatchSpec | null>(null);
  const [error, setError] = useState('');
  const jobIdRef = useRef<string | null>(null);

  const cancel = useCallback(async (): Promise<void> => {
    const jobId = jobIdRef.current;
    if (jobId === null) return;
    await jobsApi.cancel(jobId);
  }, []);

  /** 轮询一只规划作业直到终态：方案增量取回 + 失败明细透出（run/resume 共用）。 */
  const pollUntilTerminal = useCallback(
    async (jobId: string, batch: string): Promise<void> => {
      for (;;) {
        const job = await analysisApi.status(jobId);
        setPercent(job.progress);
        setStageText(job.message ?? '');
        setFailDetail(job.error ?? '');
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
    },
    [projectId],
  );

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
        setSpec({ modes: [...modes], k });
        await pollUntilTerminal(jobId, batch);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        jobIdRef.current = null;
        setPlanning(false);
        setStageText('');
      }
    },
    [planning, pollUntilTerminal, projectId],
  );

  // 页面重进：先找回在跑的规划作业（type=narration + 同 ref_id + 未终态）重新挂轮询；
  // 没有在跑作业时也要把库里已有方案捞回来——方案是持久资产，不该随导航消失。
  // 多次「生成方案」的产物按批次累积落库（不丢数据），页面只呈现**最近一批**。
  // 在跑批次的规格从项目设置恢复（服务端创建批次时写入 last_plan_batch）。
  useEffect(() => {
    if (projectId === '' || jobIdRef.current !== null) return;
    let cancelled = false;
    (async (): Promise<void> => {
      try {
        const { jobs } = await jobsApi.list(20, true);
        if (cancelled) return;
        const active = jobs.find(
          (job) =>
            job.type === 'narration' &&
            job.ref_id === projectId &&
            (job.status === 'running' || job.status === 'pending'),
        );
        const all = await narrationApi.listPlans(projectId);
        if (cancelled) return;
        if (active === undefined) {
          // 没有在跑作业：展示**最近一批**方案——跨批全量刷屏没人看得过来，
          // 旧批次仍在库里，按 created_at 找最新一批的 batch_id 圈定展示范围。
          const latest = all.reduce<NarrationPlan | null>(
            (acc, p) => (acc === null || (p.created_at ?? 0) > (acc.created_at ?? 0) ? p : acc),
            null,
          );
          const batch = latest?.batch_id ?? null;
          setBatchId(batch);
          setPlans(batch === null ? all : all.filter((p) => p.batch_id === batch));
          return;
        }
        jobIdRef.current = active.id;
        setBatchId(active.id);
        setPlanning(true);
        setPercent(active.progress);
        setStageText(active.label ?? '');
        setFailDetail(active.error ?? '');
        setPlans(all.filter((p) => p.batch_id === active.id));
        if (cancelled) return;
        try {
          const detail = await projectApi.get(projectId);
          const stored = (
            (detail.project.settings ?? {}) as Record<string, unknown>
          )['last_plan_batch'];
          if (
            !cancelled &&
            stored &&
            typeof stored === 'object' &&
            Array.isArray((stored as { modes?: unknown }).modes)
          ) {
            setSpec({
              modes: (stored as { modes: string[] }).modes as NarrationMode[],
              k: typeof (stored as { k?: unknown }).k === 'number' ? (stored as { k: number }).k : 1,
            });
          }
        } catch {
          // 规格恢复失败只影响骨架显示，不影响轮询
        }
        if (cancelled) return;
        await pollUntilTerminal(active.id, active.id);
      } catch {
        // 找回失败按「没有在跑作业」处理：不打扰用户
      } finally {
        if (!cancelled) {
          setPlanning(false);
          setStageText('');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pollUntilTerminal, projectId]);

  return { planning, percent, stageText, plans, failDetail, batchId, spec, error, run, cancel };
}
