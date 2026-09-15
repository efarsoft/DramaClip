/** 工作台数据装载：一次并发取全，服务就绪前不发请求。
 *
 * "就绪前不发"沿用 HomePage 既有的时序修复——服务就绪前发起的 RPC
 * 会失败，否则每次冷启都会打出一串红色 message。
 *
 * 五个数据源全部是既有方法，本片零后端：
 *   project.list · models.list · settings.get（只判 llm.base_url 是否为空）·
 *   export.list_works · jobs.list
 *
 * 不调 project.dashboard_summary：它唯一的用处是 project_count，而 projects.length
 * 就是同一个数；它的 export_count 反而不可用（见 stats.ts 顶部注释）。少一次 RPC。
 *
 * 不调 analysis.results：它按剧逐个取，是 N+1，且每次会把该剧全部 ASR 段拖回来。
 * 失败任务的 error 原文改从 jobs.list 拿——一次 RPC，jobs 行里有 error。
 */
import { useCallback, useEffect, useState } from 'react';
import type { JobInfo, ModelInfo, Project, WorkItem } from '@dramaclip/protocol';
import { jobsApi, listWorks, projectApi, rpc } from '../../services/client';
import { useUiStore } from '../../stores/ui';
import { WORKS_SCAN_LIMIT } from './stats';

/** jobs 扫描上限。schema 的 maximum 是 200（protocol/schemas/jobs.json），超了服务端钳回来。 */
export const JOBS_SCAN_LIMIT = 200;

export interface WorkbenchData {
  readonly projects: Project[];
  /** null = 还没取回来或取失败。buildTodos 据此区分"加载中"与"缺模型"。 */
  readonly models: ModelInfo[] | null;
  readonly llmConfigured: boolean;
  readonly jobs: JobInfo[];
  readonly serverTimeMs: number;
  readonly works: WorkItem[];
}

const EMPTY: WorkbenchData = {
  projects: [],
  models: null,
  llmConfigured: false,
  jobs: [],
  serverTimeMs: 0,
  works: [],
};

export interface Workbench {
  readonly data: WorkbenchData;
  readonly ready: boolean;
  readonly reload: () => Promise<void>;
}

export function useWorkbench(): Workbench {
  const serviceState = useUiStore((state) => state.serviceState);
  const [data, setData] = useState<WorkbenchData>(EMPTY);

  const reload = useCallback(async () => {
    const [projects, models, settings, works, jobs] = await Promise.all([
      projectApi.list(),
      rpc<ModelInfo[]>('models.list').catch(() => null),
      rpc<Record<string, string>>('settings.get').catch(() => null),
      listWorks(WORKS_SCAN_LIMIT).catch((): WorkItem[] => []),
      jobsApi.list(JOBS_SCAN_LIMIT).catch(() => null),
    ]);
    setData({
      projects,
      models,
      llmConfigured: (settings?.['llm.base_url'] ?? '') !== '',
      jobs: jobs?.jobs ?? [],
      // 服务端时钟优先：ETA 与周增都要与 created_at/completed_at 同量纲同源。
      // jobs.list 取不到时退回本机时钟——次优，但比拿 0 当"现在"好。
      serverTimeMs: jobs?.server_time_ms ?? Date.now(),
      works,
    });
  }, []);

  useEffect(() => {
    if (serviceState === 'ready') void reload();
  }, [reload, serviceState]);

  return { data, ready: serviceState === 'ready', reload };
}
