/**
 * 项目状态管理
 */

import { create } from 'zustand';
import { projectApi, type Project, type Episode } from '../services/ipc';

interface ProjectState {
  // 状态
  projects: Project[];
  currentProject: Project | null;
  currentVideos: Episode[];
  selectedEpisodeIds: string[];
  isLoading: boolean;
  error: string | null;
  clipScheme: string | null;
  clipTargetDuration: number;

  // 操作
  loadProjects: () => Promise<void>;
  createProject: (name: string, path: string) => Promise<Project>;
  openProject: (projectId: string) => Promise<Project>;
  deleteProject: (projectId: string, keepFiles?: boolean) => Promise<void>;
  importVideos: (projectId: string, paths: string[]) => Promise<Episode[]>;
  renameProject: (projectId: string, newName: string) => Promise<void>;
  loadProjectVideos: (projectId: string) => Promise<void>;
  setSelectedEpisodeIds: (ids: string[]) => void;
  setCurrentProject: (project: Project | null) => void;
  clearError: () => void;
  setClipScheme: (scheme: string | null) => void;
  setClipTargetDuration: (duration: number) => void;
}

export const useProjectStore = create<ProjectState>((set, get) => ({
  // 初始状态
  projects: [],
  currentProject: null,
  currentVideos: [],
  selectedEpisodeIds: [],
  isLoading: false,
  error: null,
  clipScheme: null,
  clipTargetDuration: 0,

  // 加载项目列表
  loadProjects: async () => {
    set({ isLoading: true, error: null });
    try {
      const projects = await projectApi.list();
      set({ projects, isLoading: false });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to load projects';
      set({ error: message, isLoading: false });
    }
  },

  // 创建项目
  createProject: async (name: string, path: string) => {
    set({ isLoading: true, error: null });
    try {
      const project = await projectApi.create(name, path);
      set((state) => ({
        projects: [...state.projects, project],
        currentProject: project,
        currentVideos: [],
        isLoading: false,
      }));
      return project;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to create project';
      set({ error: message, isLoading: false });
      throw error;
    }
  },

  // 打开项目
  openProject: async (projectId: string) => {
    set({ isLoading: true, error: null });
    try {
      const project = await projectApi.open(projectId);
      // 后端 open 已自动扫描视频目录，数据在 project.videos 中
      const storedSelected = localStorage.getItem(`dramaclip-selected-episodes-${projectId}`);
      const storedScheme = localStorage.getItem(`dramaclip-clipscheme-${projectId}`);
      const storedDuration = localStorage.getItem(`dramaclip-targetduration-${projectId}`);
      set({
        currentProject: project,
        currentVideos: project.videos ?? [],
        selectedEpisodeIds: storedSelected ? JSON.parse(storedSelected) : [],
        clipScheme: storedScheme ?? null,
        clipTargetDuration: storedDuration ? Number(storedDuration) : 0,
        isLoading: false,
      });
      return project;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to open project';
      set({ error: message, isLoading: false });
      throw error;
    }
  },

  // 删除项目
  deleteProject: async (projectId: string, keepFiles = false) => {
    set({ isLoading: true, error: null });
    try {
      await projectApi.delete(projectId, keepFiles);
      // 同时清理该项目的本地状态缓存
      localStorage.removeItem(`dramaclip-selected-episodes-${projectId}`);
      localStorage.removeItem(`dramaclip-clipscheme-${projectId}`);
      localStorage.removeItem(`dramaclip-targetduration-${projectId}`);
      localStorage.removeItem(`dramaclip-preset-${projectId}`);
      localStorage.removeItem(`dramaclip-completed-exports-${projectId}`);
      localStorage.removeItem(`dramaclip-title-result-${projectId}`);
      
      set((state) => ({
        projects: state.projects.filter((p) => p.id !== projectId),
        currentProject: state.currentProject?.id === projectId ? null : state.currentProject,
        isLoading: false,
      }));
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to delete project';
      set({ error: message, isLoading: false });
      throw error;
    }
  },

  // 导入视频
  importVideos: async (projectId: string, paths: string[]) => {
    set({ isLoading: true, error: null });
    try {
      const videos = await projectApi.importVideos(projectId, paths);
      const currentProject = get().currentProject;
      if (currentProject && currentProject.id === projectId) {
        // 重新从数据库加载最新的视频列表，保证状态与数据库完全一致。
        // 加入健壮的降级容错逻辑，防止 API 出错或测试环境 mock 未设置导致崩溃
        let latestVideos = videos;
        try {
          const fetched = await projectApi.getVideos(projectId);
          if (fetched && Array.isArray(fetched)) {
            latestVideos = fetched;
          } else {
            latestVideos = [...get().currentVideos, ...videos];
          }
        } catch {
          latestVideos = [...get().currentVideos, ...videos];
        }

        set({
          currentVideos: latestVideos,
          currentProject: {
            ...currentProject,
            episode_count: latestVideos.length,
          },
          isLoading: false,
        });
      }
      return videos;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to import videos';
      set({ error: message, isLoading: false });
      throw error;
    }
  },

  // 重命名项目
  renameProject: async (projectId: string, newName: string) => {
    set({ isLoading: true, error: null });
    try {
      const project = await projectApi.rename(projectId, newName);
      set((state) => ({
        projects: state.projects.map((p) => (p.id === projectId ? project : p)),
        currentProject: state.currentProject?.id === projectId ? project : state.currentProject,
        isLoading: false,
      }));
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to rename project';
      set({ error: message, isLoading: false });
      throw error;
    }
  },

  // 加载项目视频列表
  loadProjectVideos: async (projectId: string) => {
    set({ isLoading: true, error: null });
    try {
      const videos = await projectApi.getVideos(projectId);
      set({ currentVideos: videos, isLoading: false });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to load project videos';
      set({ error: message, isLoading: false });
      throw error;
    }
  },

  // 设置选择的视频 ID
  setSelectedEpisodeIds: (ids: string[]) => {
    const currentProject = get().currentProject;
    if (currentProject) {
      localStorage.setItem(`dramaclip-selected-episodes-${currentProject.id}`, JSON.stringify(ids));
    }
    set({ selectedEpisodeIds: ids });
  },

  // 设置当前项目
  setCurrentProject: (project: Project | null) => {
    set({ currentProject: project, currentVideos: [] });
  },

  // 清除错误
  clearError: () => {
    set({ error: null });
  },

  // 设置剪辑方案
  setClipScheme: (scheme: string | null) => {
    const currentProject = get().currentProject;
    if (currentProject) {
      if (scheme) {
        localStorage.setItem(`dramaclip-clipscheme-${currentProject.id}`, scheme);
      } else {
        localStorage.removeItem(`dramaclip-clipscheme-${currentProject.id}`);
      }
    }
    set({ clipScheme: scheme });
  },

  // 设置剪辑目标时长
  setClipTargetDuration: (duration: number) => {
    const currentProject = get().currentProject;
    if (currentProject) {
      localStorage.setItem(`dramaclip-targetduration-${currentProject.id}`, String(duration));
    }
    set({ clipTargetDuration: duration });
  },
}));
