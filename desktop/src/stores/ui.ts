import { create } from 'zustand';
import type { ServiceState } from '@dramaclip/protocol';
import { onServiceEvent } from '../services/client';

/** analysis 任务进度（progress.update 事件驱动）。 */
export interface AnalysisProgress {
  readonly jobId: string;
  readonly percent: number;
  readonly message: string;
}

/** 模型下载进度（models.download_progress 事件驱动，按 model_id 索引）。 */
export interface ModelDownloadState {
  readonly percent: number;
  readonly status: 'downloading' | 'done' | 'failed';
  /** 速度文本（如「3.2 MB/s」）；空串 = 后端算不出（刚起步，采样窗没满）。 */
  readonly speed: string;
  /** 预计剩余文本（如「3分20秒」）；空串 = 还估不出——界面显示「—」，不瞎猜。 */
  readonly eta: string;
  /** 失败原因的分类原话（后端 classify_failure 产出）；非 failed 时为空串。 */
  readonly message: string;
}

/** 仅全局 UI 状态（docs/desktop/01 §3）；域内状态留在各 feature。 */
interface UiState {
  serviceState: ServiceState;
  currentProjectId: string | null;
  analysisProgress: AnalysisProgress | null;
  modelDownloads: Record<string, ModelDownloadState>;
  setServiceState: (state: ServiceState) => void;
  setCurrentProjectId: (id: string | null) => void;
  setAnalysisProgress: (progress: AnalysisProgress | null) => void;
  setModelDownload: (modelId: string, state: ModelDownloadState) => void;
}

export const useUiStore = create<UiState>((set) => ({
  serviceState: 'starting',
  currentProjectId: null,
  analysisProgress: null,
  modelDownloads: {},
  setServiceState: (serviceState) => {
    set({ serviceState });
  },
  setCurrentProjectId: (currentProjectId) => {
    set({ currentProjectId });
  },
  setAnalysisProgress: (analysisProgress) => {
    set({ analysisProgress });
  },
  setModelDownload: (modelId, downloadState) => {
    set((state) => ({
      modelDownloads: { ...state.modelDownloads, [modelId]: downloadState },
    }));
  },
}));

/** 供路由页面以函数形式设置当前项目（避免各页直接持有 store setter）。 */
export function setCurrentProjectIdInStore(id: string | null): void {
  useUiStore.getState().setCurrentProjectId(id);
}

/** 订阅 progress.update → analysisProgress（在 App 装配一次，返回取消函数）。 */
export function subscribeAnalysisProgress(): () => void {
  return onServiceEvent((event) => {
    if (event.type !== 'notification' || event.method !== 'progress.update') return;
    const params = event.params as { job_id?: unknown; percent?: unknown; message?: unknown };
    useUiStore.getState().setAnalysisProgress({
      jobId: typeof params.job_id === 'string' ? params.job_id : '',
      percent: typeof params.percent === 'number' ? params.percent : 0,
      message: typeof params.message === 'string' ? params.message : '',
    });
  });
}

/** 订阅 models.download_progress → modelDownloads（在 App 装配一次，返回取消函数）。 */
export function subscribeModelDownloadProgress(): () => void {
  return onServiceEvent((event) => {
    if (event.type !== 'notification' || event.method !== 'models.download_progress') return;
    const params = event.params as {
      model_id?: unknown;
      percent?: unknown;
      status?: unknown;
      speed?: unknown;
      eta?: unknown;
      message?: unknown;
    };
    const modelId = typeof params.model_id === 'string' ? params.model_id : '';
    const status = params.status === 'done' || params.status === 'failed' ? params.status : 'downloading';
    if (modelId === '') return;
    useUiStore.getState().setModelDownload(modelId, {
      percent: typeof params.percent === 'number' ? params.percent : 0,
      status,
      speed: typeof params.speed === 'string' ? params.speed : '',
      eta: typeof params.eta === 'string' ? params.eta : '',
      message: typeof params.message === 'string' ? params.message : '',
    });
  });
}
