/** 分析页数据与任务编排（UI 解耦）。 */
import { useCallback, useEffect, useState } from 'react';
import type {
  AnalysisJobStatus,
  AnalysisResults,
  Episode,
  Project,
  ProjectGetResult,
} from '@dramaclip/protocol';
import { analysisApi, jobsApi, projectApi } from '../../services/client';
import { syncSelectionOnEpisodes, useDramaSelectionStore } from '../../stores/dramaSelection';
import { useUiStore } from '../../stores/ui';

/** status 轮询间隔：progress 通知仅驱动进度条，轮询是可靠性兜底。 */
const JOB_POLL_MS = 3000;

/** 终态作业：到达即触发整页重载，轮询随之停。 */
const SETTLED_STATUSES: readonly AnalysisJobStatus['status'][] = ['completed', 'failed', 'cancelled'];

/** 勾选集住在壳级 store（跨页保勾选）；本剧还没进过 store 时的空视图。 */
const EMPTY_SELECTION: readonly string[] = [];

/**
 * 把轮询拿到的实时集状态合并进列表——运行中徽章翻动的唯一通道。
 * 此前只有终态才 loadAll()，整轮分析期间集列表冻结在旧状态（点了批量分析
 * 界面毫无反应）。无变化返回原引用，React 跳过重渲染。
 */
export function mergeEpisodeStatuses(
  episodes: Episode[],
  live: readonly { episode_id: string; status: string }[] | undefined,
): Episode[] {
  if (live === undefined) return episodes;
  const byId = new Map(live.map((item) => [item.episode_id, item.status]));
  const next = episodes.map((episode) => {
    const status = byId.get(episode.id) ?? episode.status;
    return status === episode.status ? episode : { ...episode, status };
  });
  // 无变化返回原引用（逐项同引用比较）：React 跳过重渲染
  return next.every((item, index) => item === episodes[index]) ? episodes : next;
}

/** 找本项目在跑的分析/预筛作业并取其状态；没有或取不到都是 null（不阻塞页面）。 */
async function fetchActiveJob(projectId: string): Promise<AnalysisJobStatus | null> {
  try {
    const { jobs } = await jobsApi.list(50, true);
    const active = jobs.find(
      (item) =>
        item.ref_id === projectId && (item.type === 'analysis' || item.type === 'prescreen'),
    );
    return active === undefined ? null : await analysisApi.status(active.id);
  } catch {
    // 分析页仍可手点开始；任务列表取不到不能把整页卡死
    return null;
  }
}

/** 在跑作业的轮询兜底：settled 即停。 */
function useJobPolling(job: AnalysisJobStatus | null, refreshJob: (jobId: string) => Promise<void>): void {
  const activeJobId = job?.status === 'running' || job?.status === 'pending' ? job.job_id : null;
  useEffect(() => {
    if (activeJobId === null) return;
    const timer = setInterval(() => void refreshJob(activeJobId), JOB_POLL_MS);
    return () => {
      clearInterval(timer);
    };
  }, [activeJobId, refreshJob]);
}

/** 两条真启动路径：全部精转 = analysis.start（勾选集）；仅推荐集精转 = prescreen(then_analyze)。 */
function useStartActions(
  projectId: string,
  refreshJob: (jobId: string) => Promise<void>,
  selectedIds: readonly string[],
) {
  const start = useCallback(async (): Promise<void> => {
    if (selectedIds.length === 0) return;
    const { job_id } = await analysisApi.start(projectId, selectedIds);
    await refreshJob(job_id);
  }, [projectId, refreshJob, selectedIds]);

  /** 档位「仅推荐集精转」的执行体：预筛全项目待分析集，推荐集自动接精转。 */
  const startPrescreen = useCallback(async (): Promise<void> => {
    const { job_id } = await analysisApi.prescreen(projectId, true);
    await refreshJob(job_id);
  }, [projectId, refreshJob]);

  return { start, startPrescreen };
}

export function useAnalysisWorkspace(projectId: string): AnalysisWorkspace {
  const [project, setProject] = useState<Project | null>(null);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [activeEpisodeId, setActiveEpisodeId] = useState<string | null>(null);
  const [results, setResults] = useState<AnalysisResults | null>(null);
  const [job, setJob] = useState<AnalysisJobStatus | null>(null);
  const serviceState = useUiStore((state) => state.serviceState);
  const selectedIds = useDramaSelectionStore((state) =>
    state.projectId === projectId ? state.episodeIds : EMPTY_SELECTION,
  );
  const toggleEpisode = useDramaSelectionStore((state) => state.toggleEpisode);

  const applyDetail = useCallback(
    (detail: ProjectGetResult): void => {
      setProject(detail.project);
      setEpisodes(detail.episodes);
      // 首进默认勾未完成集；同剧重载保留用户勾选（卷二 §6.5）
      syncSelectionOnEpisodes(projectId, detail.episodes);
      setActiveEpisodeId(detail.episodes[0]?.id ?? null);
    },
    [projectId],
  );

  const loadAll = useCallback(async (): Promise<void> => {
    applyDetail(await projectApi.get(projectId));
    setResults(await analysisApi.results(projectId));
    const active = await fetchActiveJob(projectId);
    if (active !== null) setJob(active);
  }, [applyDetail, projectId]);

  // 服务就绪前 RPC 会失败；ready 后（重）加载一次
  useEffect(() => {
    if (serviceState === 'ready') void loadAll();
  }, [loadAll, serviceState]);

  const refreshJob = useCallback(async (jobId: string) => {
    const status = await analysisApi.status(jobId);
    setJob(status);
    setEpisodes((prev) => mergeEpisodeStatuses(prev, status.episodes));
    if (SETTLED_STATUSES.includes(status.status)) await loadAll();
  }, [loadAll]);

  useJobPolling(job, refreshJob);

  const { start, startPrescreen } = useStartActions(projectId, refreshJob, selectedIds);

  const cancel = useCallback(async (): Promise<void> => {
    if (job === null) return;
    await analysisApi.cancel(job.job_id);
    await refreshJob(job.job_id);
  }, [job, refreshJob]);

  return {
    project,
    episodes,
    selectedIds,
    toggleSelected: (episodeId, checked) => {
      toggleEpisode(projectId, episodeId, checked);
    },
    activeEpisodeId,
    setActiveEpisodeId,
    results,
    job,
    start,
    startPrescreen,
    cancel,
    reload: loadAll,
    canStart: selectedIds.length > 0 && !(job?.status === 'running' || job?.status === 'pending'),
  };
}

export interface AnalysisWorkspace {
  project: Project | null;
  episodes: Episode[];
  selectedIds: readonly string[];
  toggleSelected: (episodeId: string, checked: boolean) => void;
  activeEpisodeId: string | null;
  setActiveEpisodeId: (id: string) => void;
  results: AnalysisResults | null;
  job: AnalysisJobStatus | null;
  start: () => Promise<void>;
  startPrescreen: () => Promise<void>;
  cancel: () => Promise<void>;
  reload: () => Promise<void>;
  canStart: boolean;
}
