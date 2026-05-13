/**
 * 导出状态管理
 */

import { create } from 'zustand';

export type ExportFormat = 'mp4' | 'mkv' | 'mov';
export type VideoQuality = '4k' | '1080p' | '720p' | '480p';

export interface ExportConfig {
  format: ExportFormat;
  quality: VideoQuality;
  resolution: string;
  bitrate: number;
  fps: number;
  outputPath: string;
}

export interface ExportTask {
  id: string;
  projectId: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  message: string;
  outputPath?: string;
  error?: string;
}

interface ExportState {
  config: ExportConfig;
  currentTask: ExportTask | null;
  history: ExportTask[];

  // Actions
  setConfig: (config: Partial<ExportConfig>) => void;
  setCurrentTask: (task: ExportTask | null) => void;
  addToHistory: (task: ExportTask) => void;
  updateTaskProgress: (progress: number, message: string) => void;
}

const defaultConfig: ExportConfig = {
  format: 'mp4',
  quality: '1080p',
  resolution: '1080x1920',
  bitrate: 8000,
  fps: 30,
  outputPath: '',
};

export const useExportStore = create<ExportState>((set) => ({
  config: defaultConfig,
  currentTask: null,
  history: [],

  setConfig: (config) =>
    set((state) => ({ config: { ...state.config, ...config } })),

  setCurrentTask: (task) => set({ currentTask: task }),

  addToHistory: (task) =>
    set((state) => ({ history: [...state.history, task] })),

  updateTaskProgress: (progress, message) =>
    set((state) => ({
      currentTask: state.currentTask
        ? { ...state.currentTask, progress, message }
        : null,
    })),
}));
