/**
 * UI 全局状态管理
 */

import { create } from 'zustand';

export type BackendStatus = 'connecting' | 'ready' | 'error';

interface UiState {
  // 后端状态
  backendStatus: BackendStatus;
  setBackendStatus: (status: BackendStatus) => void;

  // 当前项目 ID
  currentProjectId: string | null;
  setCurrentProjectId: (id: string | null) => void;

  // 侧边栏折叠
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (collapsed: boolean) => void;

  // 通知
  notifications: Notification[];
  addNotification: (notification: Omit<Notification, 'id'>) => void;
  removeNotification: (id: string) => void;
}

interface Notification {
  id: string;
  type: 'info' | 'success' | 'warning' | 'error';
  message: string;
  description?: string;
}

export const useUiStore = create<UiState>((set) => ({
  backendStatus: 'connecting',
  setBackendStatus: (status) => set({ backendStatus: status }),

  currentProjectId: null,
  setCurrentProjectId: (id) => set({ currentProjectId: id }),

  sidebarCollapsed: false,
  setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),

  notifications: [],
  addNotification: (notification) =>
    set((state) => ({
      notifications: [
        ...state.notifications,
        { ...notification, id: `notification-${Date.now()}` },
      ],
    })),
  removeNotification: (id) =>
    set((state) => ({
      notifications: state.notifications.filter((n) => n.id !== id),
    })),
}));
