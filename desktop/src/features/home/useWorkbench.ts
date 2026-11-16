/** 工作台数据装载：并发取全 + 未取全时有界重试，服务就绪前不发请求。
 *
 * "就绪前不发"沿用 HomePage 既有的时序修复——服务就绪前发起的 RPC
 * 会失败，否则每次冷启都会打出一串红色 message。
 *
 * 但就绪瞬间的首查仍可能一过性失败（冷盘/杀软首扫等），一次性取数会把
 * 瞬时失败永久钉在首页（装测 2026-11-16 实锤：jobs.list 首查失败 →
 * 「任务状态取不到」卡死，直到手动重启服务）。所以五源各自容错、未取全
 * 时按 5s×6 重试取全即停——不做成无限轮询，那是 JobsFeed 的职责。
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
import type { JobInfo, JobsListResult, ModelInfo, Project, WorkItem } from '@dramaclip/protocol';
import { jobsApi, listWorks, projectApi, rpc } from '../../services/client';
import { useUiStore } from '../../stores/ui';
import { WORKS_SCAN_LIMIT } from './stats';

/** jobs 扫描上限。schema 的 maximum 是 200（protocol/schemas/jobs.json），超了服务端钳回来。 */
export const JOBS_SCAN_LIMIT = 200;

/** 未取全时的重试节奏：首轮之外最多 6 次、间隔 5s——覆盖冷启一过性失败
 *  的窗口（≈35s），之后停手交给用户可见的「重启服务」入口。 */
const RELOAD_RETRY_MAX = 6;
const RELOAD_RETRY_DELAY_MS = 5_000;

export interface WorkbenchData {
  readonly projects: Project[];
  /** null = 还没取回来或取失败。buildTodos 据此区分"加载中"与"缺模型"。 */
  readonly models: ModelInfo[] | null;
  readonly llmBaseUrl: string;
  readonly ttsEngine: string;
  readonly jobs: JobInfo[];
  /** jobs.list 是否取到；取不到时 jobsError 是原因原文。 */
  readonly jobsAvailable: boolean;
  readonly jobsError: string | null;
  readonly serverTimeMs: number;
  readonly works: WorkItem[];
}

const EMPTY: WorkbenchData = {
  projects: [],
  models: null,
  llmBaseUrl: '',
  ttsEngine: 'edge',
  jobs: [],
  jobsAvailable: false,
  jobsError: null,
  serverTimeMs: 0,
  works: [],
};

export interface Workbench {
  readonly data: WorkbenchData;
  readonly ready: boolean;
  /** 取一轮；返回是否五源全部取到（调用方据此决定是否还值得重试）。 */
  readonly reload: () => Promise<boolean>;
}

export function useWorkbench(): Workbench {
  const serviceState = useUiStore((state) => state.serviceState);
  const [data, setData] = useState<WorkbenchData>(EMPTY);

  const reload = useCallback(async (): Promise<boolean> => {
    // 五源各自容错（此前 project.list 没接 catch：它一抛整个 Promise.all 拒绝，
    // setData 不执行、五源全停留在空默认值——比单源失败更像“全新空态”）。
    let complete = true;
    const [projects, models, settings, works, jobs] = await Promise.all([
      projectApi.list().catch((): Project[] => {
        complete = false;
        return [];
      }),
      rpc<ModelInfo[]>('models.list').catch((): null => {
        complete = false;
        return null;
      }),
      rpc<Record<string, string>>('settings.get').catch((): null => {
        complete = false;
        return null;
      }),
      listWorks(WORKS_SCAN_LIMIT).catch((): WorkItem[] => {
        complete = false;
        return [];
      }),
      jobsApi
        .list(JOBS_SCAN_LIMIT)
        .then((result): JobsListResult | Error => result)
        .catch((error: unknown): JobsListResult | Error => {
          complete = false;
          return error instanceof Error ? error : new Error(String(error));
        }),
    ]);
    setData({
      projects,
      models,
      llmBaseUrl: settings?.['llm.base_url'] ?? '',
      ttsEngine: settings?.['tts.engine'] ?? 'edge',
      jobs: jobs instanceof Error ? [] : jobs.jobs,
      jobsAvailable: !(jobs instanceof Error),
      jobsError: jobs instanceof Error ? `${jobs.name}: ${jobs.message}` : null,
      // 服务端时钟优先：ETA 与周增都要与 created_at/completed_at 同量纲同源。
      // jobs.list 取不到时退回本机时钟——次优，但比拿 0 当"现在"好。
      serverTimeMs: jobs instanceof Error ? Date.now() : jobs.server_time_ms,
      works,
    });
    return complete;
  }, []);

  useEffect(() => {
    if (serviceState !== 'ready') return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    const run = (): void => {
      void reload().then((complete) => {
        if (stopped || complete) return;
        attempt += 1;
        if (attempt > RELOAD_RETRY_MAX) return;
        timer = setTimeout(run, RELOAD_RETRY_DELAY_MS);
      });
    };
    run();
    return () => {
      stopped = true;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [reload, serviceState]);

  return { data, ready: serviceState === 'ready', reload };
}
