/**
 * 历史输出管理
 * 管理剪辑任务产生的历史输出文件
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export interface OutputRecord {
  id: string;
  projectId: string;
  projectName: string;
  taskId: string;
  outputPath: string;
  fileName: string;
  fileSize: number;
  duration: number;
  quality: string;
  format: string;
  createdAt: number;
  thumbnail?: string;
}

interface OutputHistoryState {
  records: OutputRecord[];
  maxRecords: number;

  addRecord: (record: Omit<OutputRecord, 'id'>) => void;
  removeRecord: (id: string) => void;
  clearHistory: () => void;
  setMaxRecords: (max: number) => void;
  getTotalSize: () => number;
  getRecordsByProject: (projectId: string) => OutputRecord[];
}

export const useOutputHistoryStore = create<OutputHistoryState>()(
  persist(
    (set, get) => ({
      records: [],
      maxRecords: 100,

      addRecord: (record) => {
        const id = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
        set((state) => {
          const newRecords = [{ ...record, id }, ...state.records];
          if (newRecords.length > state.maxRecords) {
            newRecords.pop();
          }
          return { records: newRecords };
        });
      },

      removeRecord: (id) => {
        set((state) => ({
          records: state.records.filter((r) => r.id !== id),
        }));
      },

      clearHistory: () => {
        set({ records: [] });
      },

      setMaxRecords: (max) => {
        set((state) => {
          const newRecords = state.records.slice(0, max);
          return { records: newRecords, maxRecords: max };
        });
      },

      getTotalSize: () => {
        return get().records.reduce((sum, r) => sum + r.fileSize, 0);
      },

      getRecordsByProject: (projectId) => {
        return get().records.filter((r) => r.projectId === projectId);
      },
    }),
    {
      name: 'dramaclip-output-history',
    }
  )
);

export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
}

export function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) {
    return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }
  return `${m}:${s.toString().padStart(2, '0')}`;
}
