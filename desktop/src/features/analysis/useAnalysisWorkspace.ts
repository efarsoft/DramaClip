/** 分析页数据与任务编排（UI 解耦）。 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  AnalysisJobStatus,
  AnalysisResults,
  Episode,
  EpisodeDetailResult,
  Project,
  ProjectGetResult,
} from '@dramaclip/protocol';
import { analysisApi, jobsApi, projectApi } from '../../services/client';
import { syncSelectionOnEpisodes, useDramaSelectionStore } from '../../stores/dramaSelection';
import { useJobsStore } from '../../stores/jobs';
import { useUiStore } from '../../stores/ui';

/** status 轮询间隔：progress 通知仅驱动进度条，轮询是可靠性兜底。 */
const JOB_POLL_MS = 3000;

/** 终态作业：到达即触发整页重载，轮询随之停。 */
const SETTLED_STATUSES: readonly AnalysisJobStatus['status'][] = ['completed', 'failed', 'cancelled'];

/** 勾选集住在壳级 store（跨页保勾选）；本剧还没进过 store 时的空视图。 */
const EMPTY_SELECTION: readonly string[] = [];

/** 「集号 → 值」映射里把某一集归位；值为空（该集没有这项）则摘掉它的键。 */
function placed<T>(
  map: Readonly<Record<string, T>> | undefined,
  episodeId: string,
  value: T | null | undefined,
): Record<string, T> {
  const others = Object.fromEntries(
    Object.entries(map ?? {}).filter(([key]) => key !== episodeId),
  );
  return value === null || value === undefined ? others : { ...others, [episodeId]: value };
}

/**
 * 把单集详情并进页面状态。详情里各项是**这一集自己的**列表，页面状态是「集号 → 列表」
 * 的映射——必须按 episode_id 归位。直接把列表展开进映射得到的是 0/1/2 这种下标键，
 * 永远对不上集号（按集分拆上线时就是这么写的，分析页转写/高光/曲线/画面轨整体失效）。
 * 空列表照样落键：键在 = 这集拉过了，键不在 = 还没拉——选中集据此判断要不要拉。
 */
export function mergeEpisodeDetail(
  prev: AnalysisResults | null,
  detail: EpisodeDetailResult,
): AnalysisResults {
  const id = detail.episode_id;
  return {
    episodes: prev?.episodes ?? [],
    asr_segments: placed(prev?.asr_segments, id, detail.asr_segments),
    highlights: placed(prev?.highlights, id, detail.highlights),
    conflict_scores: placed(prev?.conflict_scores, id, detail.conflict_scores),
    prescreen: placed(prev?.prescreen, id, detail.prescreen),
    visual_tracks: placed(prev?.visual_tracks, id, detail.visual_track),
  };
}

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

/** 在跑作业的轮询兜底：settled 即停；在跑期间向 jobs 单写方登记快消费档（2s 节距）。 */
function useJobPolling(job: AnalysisJobStatus | null, refreshJob: (jobId: string) => Promise<void>): void {
  const activeJobId = job?.status === 'running' || job?.status === 'pending' ? job.job_id : null;
  const enterFast = useJobsStore((state) => state.enterFast);
  useEffect(() => {
    if (activeJobId === null) return;
    const release = enterFast();
    const timer = setInterval(() => void refreshJob(activeJobId), JOB_POLL_MS);
    return () => {
      release();
      clearInterval(timer);
    };
  }, [activeJobId, enterFast, refreshJob]);
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
  const analysisProgress = useUiStore((state) => state.analysisProgress);
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
      // 重载保留当前选中集（还在列表里的话）：分析中每完成一集都会整页重载，
      // 回回跳到第 1 集等于把用户正在看的那集抢走。首进、或选中集已不在才落第 1 集。
      setActiveEpisodeId((prev) =>
        prev !== null && detail.episodes.some((item) => item.id === prev)
          ? prev
          : (detail.episodes[0]?.id ?? null),
      );
    },
    [projectId],
  );

  /** 详情代际：整页重载 +1。重载前发出的详情晚到就丢——它读的可能是这一集转完之前
   *  的库（空列表），并进来会把「尚未转写」钉在刚转完的集上。 */
  const generation = useRef(0);
  const pendingDetail = useRef<Set<string>>(new Set());

  const loadAll = useCallback(async (): Promise<void> => {
    applyDetail(await projectApi.get(projectId));
    // 按集分拆（analysis 分批）：首屏只拉集列表摘要（纯数字），不拖全剧
    // 台词——50 集的全量 results 一口气几 MB JSON，首屏等它就是「卡死」。
    const summary = await analysisApi.episodes(projectId);
    // 已拉的详情一并作废（重跑会改它们）；选中集的那份由下方 effect 立刻补拉
    generation.current += 1;
    pendingDetail.current.clear();
    setResults({ episodes: summary.episodes });
    const active = await fetchActiveJob(projectId);
    if (active !== null) setJob(active);
  }, [applyDetail, projectId]);

  /** 拉某集详情（ASR 台词/高光/冲突/画面轨）并按集号并进页面状态，KB 级。 */
  const loadEpisodeDetail = useCallback(async (episodeId: string): Promise<void> => {
    if (pendingDetail.current.has(episodeId)) return;
    pendingDetail.current.add(episodeId);
    const born = generation.current;
    try {
      const detail = await analysisApi.episodeDetail(episodeId);
      if (born === generation.current) setResults((prev) => mergeEpisodeDetail(prev, detail));
    } catch {
      // 详情取不到不挡页面：面板保持空态，切集或整页重载会再拉
    } finally {
      if (born === generation.current) pendingDetail.current.delete(episodeId);
    }
  }, []);

  // 选中集的详情按需拉：状态里没有这集的键就拉。首屏默认选中、点击切集、整页重载
  // 清空之后——三条路共用这一处。此前只有「点击」会拉，默认选中的那集和每次重载
  // 之后的面板都是空的（「尚未转写」），任务一跑完必现。
  useEffect(() => {
    if (activeEpisodeId === null || results === null) return;
    if (results.asr_segments?.[activeEpisodeId] !== undefined) return;
    void loadEpisodeDetail(activeEpisodeId);
  }, [activeEpisodeId, results, loadEpisodeDetail]);

  // 服务就绪前 RPC 会失败；ready 后（重）加载一次
  useEffect(() => {
    if (serviceState === 'ready') void loadAll();
  }, [loadAll, serviceState]);

  const doneIdsSeen = useRef<Set<string>>(new Set());
  const lastJobId = useRef<string>("");
  const refreshJob = useCallback(
    async (jobId: string) => {
      const status = await analysisApi.status(jobId);
      setJob(status);
      // 新任务（含对已完成集的重跑）：清空已见集合，重跑完成的集也要刷新结果
      if (status.job_id !== lastJobId.current) {
        lastJobId.current = status.job_id;
        doneIdsSeen.current.clear();
      }
      // 有新完成的集就增量拉一次结果：转写/画面轨随集点亮，不等全批终结
      // （此前结果只在任务终结时刷新，批内面板一直显示旧转写——业主实测立案）。
      const doneIds = (status.episodes ?? [])
        .filter((episode) => episode.status === 'done')
        .map((episode) => episode.episode_id);
      const hasNewDone = doneIds.some((episodeId) => !doneIdsSeen.current.has(episodeId));
      if (hasNewDone) {
        for (const episodeId of doneIds) doneIdsSeen.current.add(episodeId);
        await loadAll();
      }
      setEpisodes((prev) => mergeEpisodeStatuses(prev, status.episodes));
      if (SETTLED_STATUSES.includes(status.status)) await loadAll();
    },
    [loadAll],
  );

  // progress.update 事件复活（规格 §1.4）：轮询 3s 是兜底对齐，事件到了先把
  // 进度/阶段并进 job——进度条不必等下一个轮询窗。两条写同一个 job sink。
  useEffect(() => {
    if (analysisProgress === null || job === null) return;
    if (analysisProgress.jobId !== job.job_id) return;
    if (analysisProgress.percent === job.progress && analysisProgress.message === job.message) return;
    setJob({ ...job, progress: analysisProgress.percent, message: analysisProgress.message });
  }, [analysisProgress, job]);

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
    // 切集只改选中项；详情由上方 effect 按「状态里有没有这集」统一补拉
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
