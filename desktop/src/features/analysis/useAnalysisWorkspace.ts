/** 分析页数据与任务编排（UI 解耦）。 */
import { useCallback, useEffect, useState } from 'react';
import type { AnalysisJobStatus, AnalysisResults, Episode, Project } from '@dramaclip/protocol';
import { analysisApi, projectApi } from '../../services/client';

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
  canStart: boolean;
}

export function useAnalysisWorkspace(projectId: string): AnalysisWorkspace {
  const [project, setProject] = useState<Project | null>(null);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [activeEpisodeId, setActiveEpisodeId] = useState<string | null>(null);
  const [results, setResults] = useState<AnalysisResults | null>(null);
  const [job, setJob] = useState<AnalysisJobStatus | null>(null);

  const loadProject = useCallback(async () => {
    const detail = await projectApi.get(projectId);
    setProject(detail.project);
    setEpisodes(detail.episodes);
    setSelectedIds(detail.episodes.filter((e) => e.status !== 'done').map((e) => e.id));
    setActiveEpisodeId(detail.episodes[0]?.id ?? null);
  }, [projectId]);

  const loadResults = useCallback(async () => {
    setResults(await analysisApi.results(projectId));
  }, [projectId]);

  const refreshJob = useCallback(
    async (jobId: string) => {
      const status = await analysisApi.status(jobId);
      setJob(status);
      const finished = status.status === 'completed' || status.status === 'failed';
      if (finished) await Promise.all([loadResults(), loadProject()]);
    },
    [loadProject, loadResults],
  );

  useEffect(() => {
    void loadProject().then(() => loadResults());
  }, [loadProject, loadResults]);

  // status 轮询兜底（progress 通知仅驱动进度条，不依赖其可靠性）
  const activeJobId = job?.status === 'running' || job?.status === 'pending' ? job.job_id : null;
  useEffect(() => {
    if (activeJobId === null) return;
    const timer = setInterval(() => void refreshJob(activeJobId), 3000);
    return () => {
      clearInterval(timer);
    };
  }, [activeJobId, refreshJob]);

  const start = useCallback(async () => {
    if (selectedIds.length === 0) return;
    const { job_id } = await analysisApi.start(projectId, selectedIds);
    await refreshJob(job_id);
  }, [projectId, refreshJob, selectedIds]);

  return {
    project,
    episodes,
    selectedIds,
    toggleSelected: (episodeId, checked) => {
      setSelectedIds((prev) =>
        checked ? [...prev, episodeId] : prev.filter((id) => id !== episodeId),
      );
    },
    activeEpisodeId,
    setActiveEpisodeId,
    results,
    job,
    start,
    canStart: selectedIds.length > 0 && !(job?.status === 'running' || job?.status === 'pending'),
  };
}
