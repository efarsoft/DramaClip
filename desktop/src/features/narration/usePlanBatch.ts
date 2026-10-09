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

/** 没有在跑作业：页面只呈现**最近一批**方案——跨批全量刷屏没人看得过来，
 * 旧批次仍在库里（多次「生成方案」按批次累积落库），按 created_at 找最新一批圈定。 */
function latestBatch(all: NarrationPlan[]): { batchId: string | null; plans: NarrationPlan[] } {
  const latest = all.reduce<NarrationPlan | null>(
    (acc, p) => (acc === null || p.created_at > acc.created_at ? p : acc),
    null,
  );
  const batchId = latest?.batch_id ?? null;
  return { batchId, plans: batchId === null ? all : all.filter((p) => p.batch_id === batchId) };
}

/** 在跑批次的提交规格从项目设置恢复（服务端创建批次时写入 last_plan_batch）；
 * 键缺失/形状不对返回 null（骨架显示退化，不报错）。 */
async function restoreSpec(projectId: string): Promise<PlanBatchSpec | null> {
  const detail = await projectApi.get(projectId);
  const stored: unknown = detail.project.settings.last_plan_batch;
  if (!(stored instanceof Object) || !Array.isArray((stored as { modes?: unknown }).modes)) {
    return null;
  }
  const k: unknown = (stored as { k?: unknown }).k;
  return {
    modes: (stored as { modes: NarrationMode[] }).modes,
    k: typeof k === 'number' ? k : 1,
  };
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
  // 卸载守卫必须经 stopped() 读：立即调用的异步 IIFE 按 IIFE 声明点内联分析，
  // let 布尔和对象属性都会被初始值收窄成字面量 false；函数返回类型不参与收窄。
  useEffect(() => {
    if (projectId === '' || jobIdRef.current !== null) return;
    const guard: { cancelled: boolean } = { cancelled: false };
    const stopped = (): boolean => guard.cancelled;
    void (async (): Promise<void> => {
      try {
        const { jobs } = await jobsApi.list(20, true);
        if (stopped()) return;
        const active = jobs.find(
          (job) => job.type === 'narration' && job.ref_id === projectId && (job.status === 'running' || job.status === 'pending'),
        );
        const all = await narrationApi.listPlans(projectId);
        if (stopped()) return;
        if (active === undefined) {
          const picked = latestBatch(all);
          setBatchId(picked.batchId);
          setPlans(picked.plans);
          return;
        }
        jobIdRef.current = active.id;
        setBatchId(active.id);
        setPlanning(true);
        setPercent(active.progress);
        setStageText(active.label ?? '');
        setFailDetail(active.error ?? '');
        setPlans(all.filter((p) => p.batch_id === active.id));
        if (stopped()) return;
        try {
          const restored = await restoreSpec(projectId);
          if (restored !== null && !stopped()) setSpec(restored);
        } catch {
          // 规格恢复失败只影响骨架显示，不影响轮询
        }
        if (stopped()) return;
        await pollUntilTerminal(active.id, active.id);
      } catch {
        // 找回失败按「没有在跑作业」处理：不打扰用户
      } finally {
        if (!stopped()) {
          setPlanning(false);
          setStageText('');
        }
      }
    })();
    return () => {
      guard.cancelled = true;
    };
  }, [pollUntilTerminal, projectId]);

  return { planning, percent, stageText, plans, failDetail, batchId, spec, error, run, cancel };
}
