/** 剧壳数据（P-C 第二刀：状态提升）：项目行 + 成品账自取，任务账订阅全局 store。
 *
 * JobsFeed 是全局唯一轮询点（开抽屉 2s / 关着 10s）写 stores/jobs——壳不再自拉
 * jobs.list：少一路 RPC，且阶段灯随每次快照实时点亮，不用等壳自己刷。
 * 项目行用 project.get 单剧接口（不再 list+find 全表扫）。
 * 取不到就说取不到：项目行对不上账 kind='missing' 带原因原文；成品账/任务账缺
 * 哪本灰哪几盏灯（宁灰勿假绿，卷三意见 03）。壳只读，不触发任何任务。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { Project, WorkItem } from '@dramaclip/protocol';
import { listWorks, projectApi } from '../../services/client';
import { useJobsStore } from '../../stores/jobs';
import { WORKS_SCAN_LIMIT } from '../home/stats';
import {
  activeStageOf,
  degradedFacts,
  deriveBlockNote,
  deriveStages,
  jobFactsFor,
  NO_JOB_FACTS,
  type BlockNote,
  type StageKey,
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
      /** 最近在跑任务落在哪一段 + 其进度（0-100）；没有在跑/账缺则 null。 */
      readonly activeStage: StageKey | null;
      readonly activeProgress: number | null;
      /** 成品/任务账缺席原因；null = 账全在。 */
      readonly factsError: string | null;
    };

export interface DramaFacts {
  readonly state: DramaFactsState;
  readonly reload: () => Promise<void>;
}

/** 壳自取的两本账：项目行（必须成功）与成品账（可缺席）。 */
type LocalState =
  | { readonly kind: 'loading' }
  | { readonly kind: 'missing'; readonly reason: string }
  | {
      readonly kind: 'ok';
      readonly project: Project;
      readonly works: WorkItem[] | null;
      readonly worksError: string | null;
    };

type Fetched<T> = { readonly ok: T } | { readonly error: string };

function reasonOf(error: unknown): string {
  return error instanceof Error && error.message !== '' ? error.message : String(error);
}

function toFetched<T>(value: T): Fetched<T> {
  return { ok: value };
}

function toFailed(error: unknown): Fetched<never> {
  return { error: reasonOf(error) };
}

export function useDramaFacts(projectId: string): DramaFacts {
  const [local, setLocal] = useState<LocalState>({ kind: 'loading' });
  const jobs = useJobsStore((state) => state.jobs);
  const jobsAvailable = useJobsStore((state) => state.available);
  const jobsError = useJobsStore((state) => state.error);
  const serverTimeMs = useJobsStore((state) => state.serverTimeMs);

  const reload = useCallback(async () => {
    if (projectId === '') {
      setLocal({ kind: 'missing', reason: '路由里没有剧 id' });
      return;
    }
    const [detail, works] = await Promise.all([
      projectApi.get(projectId).then((value) => toFetched(value.project), toFailed),
      listWorks(WORKS_SCAN_LIMIT).then((value) => toFetched(value), toFailed),
    ]);
    if ('error' in detail) {
      setLocal({ kind: 'missing', reason: detail.error });
      return;
    }
    setLocal({
      kind: 'ok',
      project: detail.ok,
      works: 'ok' in works ? works.ok : null,
      worksError: 'error' in works ? works.error : null,
    });
  }, [projectId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const state = useMemo<DramaFactsState>(() => {
    if (local.kind !== 'ok') return local;
    const { project, works, worksError } = local;
    const workCount = works === null ? null : works.filter((work) => work.project_id === projectId).length;
    const facts = degradedFacts(
      project.episode_count,
      workCount,
      jobsAvailable ? jobFactsFor(projectId, jobs) : NO_JOB_FACTS,
    );
    const stages = deriveStages(facts);
    const note = deriveBlockNote(facts, stages, {
      dramaId: projectId,
      createdAtMs: project.created_at,
      // 任务账缺席时服务端时钟也缺席：传 0 让「停滞 N 天」自然算不成立，不掺本机时钟。
      serverTimeMs: serverTimeMs ?? 0,
    });
    const problems: string[] = [];
    if (worksError !== null) problems.push(`成品账取不到：${worksError}`);
    if (!jobsAvailable) problems.push(jobsError !== null ? `任务账取不到：${jobsError}` : '任务账还没取到');
    return {
      kind: 'ok',
      project,
      stages,
      note,
      activeStage: activeStageOf(facts.activeTypes),
      activeProgress: facts.activeProgress,
      factsError: problems.length > 0 ? problems.join('；') : null,
    };
  }, [local, jobs, jobsAvailable, jobsError, serverTimeMs, projectId]);

  return { state, reload };
}
