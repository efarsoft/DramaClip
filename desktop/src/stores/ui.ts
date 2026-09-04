import { create } from 'zustand';
import type { ServiceState } from '@dramaclip/protocol';

/** 仅全局 UI 状态（docs/desktop/01 §3）；域内状态留在各 feature。 */
interface UiState {
  serviceState: ServiceState;
  currentProjectId: string | null;
  setServiceState: (state: ServiceState) => void;
  setCurrentProjectId: (id: string | null) => void;
}

export const useUiStore = create<UiState>((set) => ({
  serviceState: 'starting',
  currentProjectId: null,
  setServiceState: (serviceState) => { set({ serviceState }); },
  setCurrentProjectId: (currentProjectId) => { set({ currentProjectId }); },
}));
