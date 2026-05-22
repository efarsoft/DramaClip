/**
 * 项目相关类型定义
 */

export interface Project {
  id: string;
  name: string;
  path: string;
  created_at: string;
  updated_at: string;
  episode_count?: number;
  status?: ProjectStatus;
}

export type ProjectStatus = 'idle' | 'analyzing' | 'editing' | 'exporting' | 'error';

export interface Video {
  id: string;
  project_id: string;
  name: string;
  path: string;
  duration?: number;
  size?: number;
  sort_order?: number;
  created_at?: string;
  thumbnail_path?: string;
}

export interface ProjectCreateParams {
  name: string;
  path?: string;
}

export interface ProjectOpenResult extends Project {
  videos: Video[];
}

export interface VideoImportParams {
  project_id: string;
  paths: string[];
}

export interface VideoOrderItem {
  id: string;
  sort_order: number;
}
