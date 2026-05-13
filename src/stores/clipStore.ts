/**
 * 剪辑状态管理
 */

import { create } from 'zustand';

export type ClipMode = 'highlight' | 'transition' | 'narration';

export interface ClipSegment {
  id: string;
  episodeId: string;
  startTime: number;
  endTime: number;
  duration: number;
  score: number;
  selected: boolean;
  audioType: 'original' | 'tts';
  narration?: string;
}

export interface ClipTask {
  id: string;
  projectId: string;
  mode: ClipMode;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  message: string;
}

interface ClipState {
  clipMode: ClipMode;
  segments: ClipSegment[];
  currentTask: ClipTask | null;

  // Actions
  setClipMode: (mode: ClipMode) => void;
  setSegments: (segments: ClipSegment[]) => void;
  updateSegment: (id: string, updates: Partial<ClipSegment>) => void;
  toggleSegmentSelection: (id: string) => void;
  setCurrentTask: (task: ClipTask | null) => void;
  updateTaskProgress: (progress: number, message: string) => void;
  clearSegments: () => void;
}

export const useClipStore = create<ClipState>((set) => ({
  clipMode: 'highlight',
  segments: [],
  currentTask: null,

  setClipMode: (mode) => set({ clipMode: mode }),

  setSegments: (segments) => set({ segments }),

  updateSegment: (id, updates) =>
    set((state) => ({
      segments: state.segments.map((s) =>
        s.id === id ? { ...s, ...updates } : s
      ),
    })),

  toggleSegmentSelection: (id) =>
    set((state) => ({
      segments: state.segments.map((s) =>
        s.id === id ? { ...s, selected: !s.selected } : s
      ),
    })),

  setCurrentTask: (task) => set({ currentTask: task }),

  updateTaskProgress: (progress, message) =>
    set((state) => ({
      currentTask: state.currentTask
        ? { ...state.currentTask, progress, message }
        : null,
    })),

  clearSegments: () => set({ segments: [] }),
}));
