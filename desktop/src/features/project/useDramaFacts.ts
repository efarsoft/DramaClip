/** 剧壳数据：单部剧的项目行 + 成品账 + 任务账 → 阶段灯与卡点句（纯派生复用 stageState）。
 *
 * 取不到就说取不到：项目行都拿不到时 kind='missing' 带原因原文；账本缺一本时
 * 灯全灰、卡点句缺席——宁灰勿假绿（卷三意见 03）。壳只读，不触发任何任务。
 */
import { useCallback, useEffect, useState } from 'react';
import type { JobsListResult, Project, WorkItem } from '@dramaclip/protocol';
import { jobsApi, listWorks, projectApi } from '../../services/client';
import { WORKS_SCAN_LIMIT } from '../home/stats';
import { JOBS_SCAN_LIMIT } from '../home/useWorkbench';
import {
  degradedFacts,
  deriveBlockNote,
  deriveStages,
  jobFactsFor,
  UNKNOWN_STAGES,
  type BlockNote,
  type StageMap,
} from '../stages/stageState';

export type DramaFactsState =
  | { readonly kind: 'loading' }
  | { readonly kind: 'missing'; readonly reason: string }
  | {
      readonly kind: 'ok';
      readonly project: Project;
      readonly stages: StageMap;
      readonly note: BlockNote | null;
      /** 成品/任务账缺席原因；null = 账全在。 */
      readonly factsError: string | null;
    };

export interface DramaFacts {
  readonly state: DramaFactsState;
  readonly reload: () => Promise<void>;
}

function reasonOf(error: unknown): string {
  return error instanceof Error && error.message !== '' ? error.message : String(error);
}

export function useDramaFacts(projectId: string): DramaFacts {
  const [state, setState] = useState<DramaFactsState>({ kind: 'loading' });

  const reload = useCallback(async () => {
    if (projectId === '') {
      setState({ kind: 'missing', reason: '路由里没有剧 id' });
      return;
    }
    let projects: Project[];
    try {
      projects = await projectApi.list();
    } catch (error) {
      setState({ kind: 'missing', reason: `剧列表取不到：${reasonOf(error)}` });
      return;
    }
    const project = projects.find((candidate) => candidate.id === projectId);
    if (project === undefined) {
      setState({ kind: 'missing', reason: '剧列表里没有这部剧：它可能已被删除' });
      return;
    }
    const [works, jobsResult] = await Promise.all([
      listWorks(WORKS_SCAN_LIMIT).then(
        (value): WorkItem[] | null => value,
        (): null => null,
      ),
      jobsApi.list(JOBS_SCAN_LIMIT).then(
        (value): JobsListResult | null => value,
        (): null => null,
      ),
    ]);
    if (works === null || jobsResult === null) {
      const problems: string[] = [];
      if (works === null) problems.push('成品账取不到');
      if (jobsResult === null) problems.push('任务账取不到');
      setState({
        kind: 'ok',
        project,
        stages: { ...UNKNOWN_STAGES, intake: project.episode_count > 0 ? 'done' : 'idle' },
        note: null,
        factsError: problems.join('；'),
      });
      return;
    }
    const workCount = works.filter((work) => work.project_id === projectId).length;
    const facts = degradedFacts(project.episode_count, workCount, jobFactsFor(projectId, jobsResult.jobs));
    const stages = deriveStages(facts);
    const note = deriveBlockNote(facts, stages, {
      dramaId: projectId,
      createdAtMs: project.created_at,
      serverTimeMs: jobsResult.server_time_ms,
    });
    setState({ kind: 'ok', project, stages, note, factsError: null });
  }, [projectId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { state, reload };
}
