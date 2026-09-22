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
import { useUiStore } from '../../stores/ui';

/** status 轮询间隔：progress 通知仅驱动进度条，轮询是可靠性兜底。 */
const JOB_POLL_MS = 3000;

/** 终态作业：到达即触发整页重载，轮询随之停。 */
const SETTLED_STATUSES: readonly AnalysisJobStatus['status'][] = ['completed', 'failed', 'cancelled'];

function defaultSelection(episodes: Episode[]): string[] {
  return episodes.filter((e) => e.status !== 'done').map((e) => e.id);
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

export function useAnalysisWorkspace(projectId: string): AnalysisWorkspace {
  const [project, setProject] = useState<Project | null>(null);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [activeEpisodeId, setActiveEpisodeId] = useState<string | null>(null);
  const [results, setResults] = useState<AnalysisResults | null>(null);
  const [job, setJob] = useState<AnalysisJobStatus | null>(null);
  const serviceState = useUiStore((state) => state.serviceState);

  const applyDetail = useCallback((detail: ProjectGetResult): void => {
    setProject(detail.project);
    setEpisodes(detail.episodes);
    setSelectedIds(defaultSelection(detail.episodes));
    setActiveEpisodeId(detail.episodes[0]?.id ?? null);
  }, []);

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
    if (SETTLED_STATUSES.includes(status.status)) await loadAll();
  }, [loadAll]);

  useJobPolling(job, refreshJob);

  const start = useCallback(async (): Promise<void> => {
    if (selectedIds.length === 0) return;
    const { job_id } = await analysisApi.start(projectId, selectedIds);
    await refreshJob(job_id);
  }, [projectId, refreshJob, selectedIds]);

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
      setSelectedIds((prev) => (checked ? [...prev, episodeId] : prev.filter((id) => id !== episodeId)));
    },
    activeEpisodeId,
    setActiveEpisodeId,
    results,
    job,
    start,
    cancel,
    reload: loadAll,
    canStart: selectedIds.length > 0 && !(job?.status === 'running' || job?.status === 'pending'),
  };
}

export interface AnalysisWorkspace {
  project: Project | null;
  episodes: Episode[];
  selectedIds: string[];
  toggleSelected: (episodeId: string, checked: boolean) => void;
  activeEpisodeId: string | null;
  setActiveEpisodeId: (id: string) => void;
  results: AnalysisResults | null;
  job: AnalysisJobStatus | null;
  start: () => Promise<void>;
  cancel: () => Promise<void>;
  reload: () => Promise<void>;
  canStart: boolean;
}
