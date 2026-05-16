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
}

export const useProjectStore = create<ProjectState>((set, get) => ({
  // 初始状态
  projects: [],
  currentProject: null,
  currentVideos: [],
  selectedEpisodeIds: [],
  isLoading: false,
  error: null,

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
      set({
        currentProject: project,
        currentVideos: project.videos ?? [],
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
        set((state) => ({
          currentVideos: [...state.currentVideos, ...videos],
          currentProject: {
            ...state.currentProject!,
            episode_count: state.currentVideos.length + videos.length,
          },
          isLoading: false,
        }));
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
      console.warn('Failed to load project videos:', error);
      set({ isLoading: false });
      throw error; // 让调用方（如刷新按钮）感知错误
    }
  },

  // 设置选择的视频 ID
  setSelectedEpisodeIds: (ids: string[]) => {
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
}));
