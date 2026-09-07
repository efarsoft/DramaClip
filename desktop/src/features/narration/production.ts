/** 出片流水线：选中模式 → 编排/配音 → 自动渲染 → 成品（前端串联既有 job 原语）。 */
import { useCallback, useState } from 'react';
import type { NarrationMode, NarrationPlan } from '@dramaclip/protocol';
import { analysisApi, exportApi, narrationApi } from '../../services/client';

export type ProduceStage = 'planning' | 'rendering' | 'done' | 'failed';

export interface ProduceTask {
  readonly mode: NarrationMode;
  readonly stage: ProduceStage;
  readonly percent: number;
  readonly note: string;
}

type Patch = (mode: NarrationMode, data: Partial<ProduceTask>) => void;

const sleep = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, ms));

async function waitJob(jobId: string, onPercent?: (percent: number) => void): Promise<void> {
  for (;;) {
    const status = await analysisApi.status(jobId);
    if (status.status === 'completed') return;
    if (status.status === 'failed' || status.status === 'cancelled') {
      throw new Error(status.error ?? '任务失败');
    }
    onPercent?.(status.progress);
    await sleep(1500);
  }
}

function newestReadyPlan(plans: NarrationPlan[], mode: NarrationMode): NarrationPlan | null {
  const candidates = plans
    .filter((plan) => plan.narration_mode === mode && plan.status === 'ready')
    .sort((a, b) => (a.created_at > b.created_at ? -1 : 1));
  return candidates[0] ?? null;
}

async function renderPlan(
  patch: Patch,
  mode: NarrationMode,
  plan: NarrationPlan,
): Promise<void> {
  patch(mode, { stage: 'rendering', note: '渲染成片中' });
  const { job_id } = await exportApi.start(plan.id);
  await waitJob(job_id, (percent) => {
    patch(mode, { percent: 30 + Math.round(percent * 0.7) });
  });
  patch(mode, { stage: 'done', percent: 100, note: '已完成 · 见作品库' });
}

async function produce(
  projectId: string,
  modes: NarrationMode[],
  patch: Patch,
  setPlanningPercent: (percent: number) => void,
): Promise<void> {
  const { job_id } = await narrationApi.generatePlans(projectId, modes);
  await waitJob(job_id, setPlanningPercent);
  const plans = await narrationApi.listPlans(projectId);
  for (const mode of modes) {
    const plan = newestReadyPlan(plans, mode);
    if (plan === null) {
      patch(mode, { stage: 'failed', note: '编排未生成（可能素材不足）' });
      continue;
    }
    try {
      await renderPlan(patch, mode, plan);
    } catch (error) {
      patch(mode, {
        stage: 'failed',
        note: error instanceof Error ? error.message : String(error),
      });
    }
  }
}

export function useProduction(projectId: string): {
  tasks: ProduceTask[];
  running: boolean;
  run: (modes: NarrationMode[]) => Promise<void>;
} {
  const [tasks, setTasks] = useState<ProduceTask[]>([]);
  const [running, setRunning] = useState(false);

  const patch = useCallback((mode: NarrationMode, data: Partial<ProduceTask>) => {
    setTasks((prev) => prev.map((task) => (task.mode === mode ? { ...task, ...data } : task)));
  }, []);

  const run = useCallback(
    async (modes: NarrationMode[]): Promise<void> => {
      if (modes.length === 0 || running) return;
      setRunning(true);
      setTasks(
        modes.map((mode) => ({ mode, stage: 'planning' as const, percent: 0, note: '编排与配音中' })),
      );
      const setPlanningPercent = (percent: number): void => {
        setTasks((prev) =>
          prev.map((task) => (task.stage === 'planning' ? { ...task, percent } : task)),
        );
      };
      try {
        await produce(projectId, modes, patch, setPlanningPercent);
      } catch (error) {
        const note = error instanceof Error ? error.message : String(error);
        setTasks((prev) =>
          prev.map((task) => (task.stage === 'done' ? task : { ...task, stage: 'failed', note })),
        );
      } finally {
        setRunning(false);
      }
    },
    [patch, projectId, running],
  );

  return { tasks, running, run };
}
