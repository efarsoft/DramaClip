import { create } from 'zustand';
import type { ServiceState } from '@dramaclip/protocol';
import { onServiceEvent } from '../services/client';

/** analysis 任务进度（progress.update 事件驱动）。 */
export interface AnalysisProgress {
  readonly jobId: string;
  readonly percent: number;
  readonly message: string;
}

/** 仅全局 UI 状态（docs/desktop/01 §3）；域内状态留在各 feature。 */
interface UiState {
  serviceState: ServiceState;
  currentProjectId: string | null;
  analysisProgress: AnalysisProgress | null;
  setServiceState: (state: ServiceState) => void;
  setCurrentProjectId: (id: string | null) => void;
  setAnalysisProgress: (progress: AnalysisProgress | null) => void;
}

export const useUiStore = create<UiState>((set) => ({
  serviceState: 'starting',
  currentProjectId: null,
  analysisProgress: null,
  setServiceState: (serviceState) => {
    set({ serviceState });
  },
  setCurrentProjectId: (currentProjectId) => {
    set({ currentProjectId });
  },
  setAnalysisProgress: (analysisProgress) => {
    set({ analysisProgress });
  },
}));

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
