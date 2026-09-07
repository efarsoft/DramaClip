/** 渲染层唯一 IPC 出口（docs/desktop/01 §4）。组件禁止直接调 window.dramaclip。 */
import type {
  AnalysisJobStatus,
  ModelInfo,
  AnalysisResults,
  DashboardSummary,
  DramaClipBridge,
  ExportJob,
  HealthResult,
  NarrationMode,
  NarrationPlan,
  PingResult,
  Project,
  ProjectGetResult,
  ScannedEpisode,
  ServiceEvent,
} from '@dramaclip/protocol';

function bridge(): DramaClipBridge {
  return window.dramaclip;
}

export function rpc<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
  return bridge().rpc(method, params) as Promise<T>;
}

export function appVersion(): Promise<string> {
  return bridge().appVersion();
}

export function restartService(): Promise<void> {
  return bridge().restartService();
}

export function pickFolder(): Promise<string | null> {
  return bridge().pickFolder();
}

export function revealInFolder(path: string): Promise<void> {
  return bridge().revealInFolder(path);
}

export function windowControl(action: 'minimize' | 'maximize-toggle' | 'close'): Promise<void> {
  return bridge().windowControl(action);
}

/** 本地媒体预览 URL（dramaclip:// 协议，主进程注册）。 */
export function mediaUrl(path: string): string {
  return `dramaclip://local/${encodeURIComponent(path)}`;
}

export function onServiceEvent(callback: (event: ServiceEvent) => void): () => void {
  return bridge().onServiceEvent(callback);
}

export const systemApi = {
  ping: (): Promise<PingResult> => rpc<PingResult>('system.ping'),
  health: (): Promise<HealthResult> => rpc<HealthResult>('system.health'),
} as const;

export const projectApi = {
  create: (name: string, sourcePath: string): Promise<Project> =>
    rpc<Project>('project.create', { name, source_path: sourcePath }),
  list: (): Promise<Project[]> => rpc<Project[]>('project.list'),
  get: (projectId: string): Promise<ProjectGetResult> =>
    rpc<ProjectGetResult>('project.get', { project_id: projectId }),
  remove: (projectId: string): Promise<{ ok: boolean }> =>
    rpc<{ ok: boolean }>('project.delete', { project_id: projectId }),
  rename: (projectId: string, name: string): Promise<Project> =>
    rpc<Project>('project.rename', { project_id: projectId, name }),
  duplicate: (projectId: string): Promise<Project> =>
    rpc<Project>('project.duplicate', { project_id: projectId }),
  scanEpisodes: (projectId: string): Promise<ScannedEpisode[]> =>
    rpc<ScannedEpisode[]>('project.scan_episodes', { project_id: projectId }),
  dashboardSummary: (): Promise<DashboardSummary> => rpc<DashboardSummary>('project.dashboard_summary'),
} as const;

export const analysisApi = {
  start: (projectId: string, episodeIds?: string[]): Promise<{ job_id: string }> =>
    rpc<{ job_id: string }>(
      'analysis.start',
      episodeIds ? { project_id: projectId, episode_ids: episodeIds } : { project_id: projectId },
    ),
  status: (jobId: string): Promise<AnalysisJobStatus> =>
    rpc<AnalysisJobStatus>('analysis.status', { job_id: jobId }),
  cancel: (jobId: string): Promise<{ ok: boolean }> =>
    rpc<{ ok: boolean }>('analysis.cancel', { job_id: jobId }),
  resyncSemantic: (projectId: string, episodeId: string): Promise<{ job_id: string }> =>
    rpc<{ job_id: string }>('analysis.resync_semantic', {
      project_id: projectId,
      episode_id: episodeId,
    }),
  results: (projectId: string): Promise<AnalysisResults> =>
    rpc<AnalysisResults>('analysis.results', { project_id: projectId }),
} as const;

export const narrationApi = {
  generatePlans: (
    projectId: string,
    modes: NarrationMode[],
    episodeIds?: string[],
  ): Promise<{ job_id: string }> =>
    rpc<{ job_id: string }>(
      'narration.generate_plans',
      episodeIds ? { project_id: projectId, modes, episode_ids: episodeIds } : { project_id: projectId, modes },
    ),
  listPlans: (projectId: string): Promise<NarrationPlan[]> =>
    rpc<NarrationPlan[]>('narration.list_plans', { project_id: projectId }),
} as const;

export const exportApi = {
  start: (planId: string): Promise<{ job_id: string }> =>
    rpc<{ job_id: string }>('export.start', { plan_id: planId }),
  list: (projectId: string): Promise<ExportJob[]> =>
    rpc<ExportJob[]>('export.list', { project_id: projectId }),
} as const;

export const modelsApi = {
  list: (): Promise<ModelInfo[]> => rpc<ModelInfo[]>('models.list'),
  download: (modelId: string): Promise<{ job_id: string }> =>
    rpc<{ job_id: string }>('models.download', { model_id: modelId }),
  scanLocal: (): Promise<{ installed: ModelInfo[]; total: number }> =>
    rpc<{ installed: ModelInfo[]; total: number }>('models.scan_local'),
  remove: (modelId: string): Promise<{ ok: boolean }> =>
    rpc<{ ok: boolean }>('models.delete', { model_id: modelId }),
} as const;

export const settingsApi = {
  get: (): Promise<Record<string, string>> => rpc<Record<string, string>>('settings.get'),
  update: (values: Record<string, string>): Promise<{ ok: boolean }> =>
    rpc<{ ok: boolean }>('settings.update', { values }),
} as const;
