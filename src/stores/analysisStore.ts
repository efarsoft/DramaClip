/**
 * 视频分析状态管理
 */

import { create } from 'zustand';
import {
  analyzeApi,
  ipcClient,
  type AnalysisStatus,
} from '../services/ipc';
import type { ProgressPayload } from '../types/ipc';

interface AnalysisState {
  // 状态
  taskId: string | null;
  isAnalyzing: boolean;
  progress: number;
  phase: string;
  message: string;
  asrResults: Array<{
    start: number;
    end: number;
    text: string;
    speaker: string;
  }>;
  error: string | null;

  // 操作
  startAnalysis: (projectId: string, episodeIds?: string[]) => Promise<string>;
  cancelAnalysis: () => Promise<void>;
  setAsrResults: (results: any[]) => void;
  getResults: () => Promise<AnalysisStatus | null>;
  reset: () => void;
}

export const useAnalysisStore = create<AnalysisState>((set, get) => {
  // 注册进度监听
  ipcClient.onProgress((payload: ProgressPayload) => {
    const { task_id: taskId, progress, phase, message } = payload;
    const currentTaskId = get().taskId;
    if (taskId === currentTaskId) {
      set({ progress, phase, message });
      if (progress >= 100 || phase === 'completed') {
        set({ isAnalyzing: false });
      }
    }
  });

  return {
    // 初始状态
    taskId: null,
    isAnalyzing: false,
    progress: 0,
    phase: '',
    message: '',
    asrResults: [],
    error: null,

    // 开始分析
    startAnalysis: async (projectId: string, episodeIds?: string[]) => {
      const { taskId: existingTaskId } = get();
      if (existingTaskId) {
        throw new Error('已有正在进行的分析任务');
      }

      try {
        const response = await analyzeApi.start(projectId, episodeIds ?? []);
        const { task_id: taskId } = response;

        if (!taskId) {
          throw new Error('未获取到任务ID');
        }

        set({
          taskId,
          isAnalyzing: true,
          error: null,
          progress: 0,
          phase: '',
          message: '任务已启动',
        });

        return taskId;
      } catch (error) {
        const message = error instanceof Error ? error.message : '分析启动失败';
        set({ error: message, isAnalyzing: false });
        throw error;
      }
    },

    // 取消分析
    cancelAnalysis: async () => {
      const { taskId } = get();
      if (!taskId) return;

      try {
        await analyzeApi.cancel(taskId);
        set({
          taskId: null,
          isAnalyzing: false,
          progress: 0,
          phase: 'cancelled',
          message: '已取消',
        });
      } catch (error) {
        const message = error instanceof Error ? error.message : '取消失败';
        set({ error: message });
        throw error;
      }
    },

    // 设置ASR结果
    setAsrResults: (results: any[]) => {
      set({ asrResults: results });
    },

    // 获取结果
    getResults: async () => {
      const { taskId } = get();
      if (!taskId) return null;

      try {
        const response = await analyzeApi.getStatus(taskId);
        return response ?? null;
      } catch (error) {
        const message = error instanceof Error ? error.message : '获取结果失败';
        set({ error: message });
        throw error;
      }
    },

    // 重置
    reset: () => {
      set({
        taskId: null,
        isAnalyzing: false,
        progress: 0,
        phase: '',
        message: '',
        asrResults: [],
        error: null,
      });
    },
  };
});
