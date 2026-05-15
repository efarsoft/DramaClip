/**
 * IPC 通信客户端
 * 封装 ipcRenderer.invoke，提供类型安全的 API 调用
 */

import type { ElectronAPI, ProgressPayload } from '../../main/preload';

declare global {
  interface Window {
    electronAPI: ElectronAPI;
  }
}

// ============================================================================
// 类型定义
// ============================================================================

export interface IpcResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: IpcError;
}

export interface IpcError {
  code: number;
  message: string;
  data?: unknown;
}

export interface ProgressCallback {
  (payload: ProgressPayload): void;
}

export interface LogCallback {
  (message: string, level: string): void;
}

// ============================================================================
// IPC 调用封装
// ============================================================================

class IpcClient {
  private progressCallbacks: Set<ProgressCallback> = new Set();
  private logCallbacks: Set<LogCallback> = new Set();
  private unsubscribeFunctions: (() => void)[] = [];
  private initialized = false;

  /**
   * 初始化 IPC 监听器
   */
  init(): void {
    if (this.initialized || !window.electronAPI) {
      return;
    }

    // 监听后端进度
    const unsubProgress = window.electronAPI.backend.onProgress((payload) => {
      this.progressCallbacks.forEach((cb) => cb(payload));
    });
    this.unsubscribeFunctions.push(unsubProgress);

    // 监听后端日志
    const unsubLog = window.electronAPI.backend.onLog((message, level) => {
      this.logCallbacks.forEach((cb) => cb(message, level));
    });
    this.unsubscribeFunctions.push(unsubLog);

    this.initialized = true;
  }

  /**
   * 清理 IPC 监听器
   */
  destroy(): void {
    this.unsubscribeFunctions.forEach((unsub) => unsub());
    this.unsubscribeFunctions = [];
    this.progressCallbacks.clear();
    this.logCallbacks.clear();
    this.initialized = false;
  }

  /**
   * 注册进度回调
   */
  onProgress(callback: ProgressCallback): () => void {
    this.progressCallbacks.add(callback);
    return () => this.progressCallbacks.delete(callback);
  }

  /**
   * 执行后端调用
   */
  async call<T = unknown>(
    method: string,
    params?: Record<string, unknown>,
    timeout?: number
  ): Promise<T> {
    if (window.electronAPI) {
      const response = await window.electronAPI.backend.call<T>(method, params);
      if (!response.success) {
        const error = response.error;
        const message = error?.message || 'Unknown error';
        const code = error?.code || -32000;
        throw new IpcException(code, message, error?.data);
      }
      return response.data as T;
    }
    // Dev mode: no backend available
    throw new IpcException(-32000, 'No backend available in dev mode');
  }
}

/**
 * IPC 异常
 */
export class IpcException extends Error {
  code: number;
  data?: unknown;

  constructor(code: number, message: string, data?: unknown) {
    super(message);
    this.name = 'IpcException';
    this.code = code;
    this.data = data;
  }
}

// 单例
export const ipcClient = new IpcClient();

// ============================================================================
// API 命名空间
// ============================================================================

// 项目相关 API
export const projectApi = {
  list: () => ipcClient.call<Project[]>('project.list'),
  create: (name: string, path: string) =>
    ipcClient.call<Project>('project.create', { name, path }),
  open: (projectId: string) =>
    ipcClient.call<Project>('project.open', { project_id: projectId }),
  delete: (projectId: string) =>
    ipcClient.call<{ success: boolean }>('project.delete', { project_id: projectId }),
  rename: (projectId: string, newName: string) =>
    ipcClient.call<Project>('project.rename', { project_id: projectId, new_name: newName }),
  getVideos: (projectId: string) =>
    ipcClient.call<Episode[]>('project.getVideos', { project_id: projectId }),
  importVideos: (projectId: string, paths: string[]) =>
    ipcClient.call<Episode[]>('project.importVideos', {
      project_id: projectId,
      paths,
    }),
};

// 分析相关 API
export const analyzeApi = {
  start: (projectId: string, episodeIds: string[]) =>
    ipcClient.call<{ task_id: string }>('analyze.start', {
      project_id: projectId,
      episode_ids: episodeIds,
    }),
  getStatus: (taskId: string) =>
    ipcClient.call<AnalysisStatus>('analyze.getStatus', { task_id: taskId }),
  cancel: (taskId: string) =>
    ipcClient.call<{ success: boolean }>('analyze.cancel', { task_id: taskId }),
};

// 剪辑相关 API
export const clipApi = {
  recommend: (projectId: string) =>
    ipcClient.call<ClipRecommendation>('clip.recommend', {
      project_id: projectId,
    }),
  execute: (projectId: string, scheme: string, params: Record<string, unknown>) =>
    ipcClient.call<{ task_id: string }>('clip.execute', {
      project_id: projectId,
      scheme,
      params,
    }),
  getProgress: (taskId: string) =>
    ipcClient.call<ClipProgress>('clip.getProgress', { task_id: taskId }),
  preview: (projectId: string, scheme: string) =>
    ipcClient.call<{ preview_url: string }>('clip.preview', {
      project_id: projectId,
      scheme,
    }),
};

// 导出相关 API
export const exportApi = {
  start: (projectId: string, outputConfig: Record<string, unknown>) =>
    ipcClient.call<{ task_id: string }>('export.start', {
      project_id: projectId,
      output_config: outputConfig,
    }),
  getProgress: (taskId: string) =>
    ipcClient.call<ExportProgress>('export.getProgress', { task_id: taskId }),
};

// 设置相关 API
export const settingsApi = {
  get: () => ipcClient.call<AppSettings>('settings.get'),
  update: (settings: Partial<AppSettings>) =>
    ipcClient.call<{ success: boolean }>('settings.update', settings),
};

// 系统相关 API
export const systemApi = {
  getVersion: () => ipcClient.call<{ version: string; name: string }>('system.getVersion'),
  getFFmpegInfo: () =>
    ipcClient.call<{ available: boolean; version: string; hwaccel: string }>(
      'system.getFFmpegInfo'
    ),
  ping: () => ipcClient.call<{ pong: boolean }>('system.ping', { timestamp: Date.now() }),
};

// ---- 模型管理 ----

export interface ModelInfo {
  id: string;
  name: string;
  category: 'asr' | 'tts';
  type: 'whisper' | 'styletts2';
  size_mb: number;
  description: string;
  downloaded: boolean;
  disk_size_bytes: number;
}

export const modelApi = {
  list: () => ipcClient.call<ModelInfo[]>('model.list'),
  download: (modelId: string) =>
    ipcClient.call<{ success: boolean; model_id: string; status: string }>('model.download', {
      model_id: modelId,
    }),
  cancel: (modelId: string) =>
    ipcClient.call<{ success: boolean; model_id: string }>('model.cancel', {
      model_id: modelId,
    }),
  delete: (modelId: string) =>
    ipcClient.call<{ success: boolean; model_id: string }>('model.delete', {
      model_id: modelId,
    }),
  status: (modelId: string) =>
    ipcClient.call<{ downloading: boolean; model_id: string }>('model.status', {
      model_id: modelId,
    }),
};

// ============================================================================
// 类型定义
// ============================================================================

// ============================================================================
// 类型定义
// ============================================================================

// ─── 剪辑配置 ───
export interface ClipConfig {
  mode: 'highlight' | 'transition' | 'narration';  // 剪辑模式
  scheme: 'original_narration' | 'hybrid_narration' | 'full_narration' | 'all_narrations';  // 解说方案
  outputSize: '16:9' | '9:16' | '1:1';  // 输出尺寸
  outputQuality: '720p' | '1080p' | '2K' | '4K';  // 输出质量
  versions: number;  // 生成版本数
  targetDuration?: number;  // 目标时长（秒），0=不限
}

export interface SceneClip {
  id: string;
  videoId: string;
  sceneIndex: number;
  start: number;  // 起始秒
  end: number;    // 结束秒
  score: number;
  selected: boolean;
  duration: number;
}

export interface ClipResult {
  taskId: string;
  status: string;
  progress: number;
  phase: string;
  message: string;
  outputPaths?: string[];  // 多版本输出路径
}

export interface Project {
  id: string;
  name: string;
  path: string;
  created_at?: string;
  updated_at?: string;
  episode_count: number;
  status: 'idle' | 'analyzing' | 'ready' | 'clipping' | 'exporting';
}

export interface Episode {
  id: string;
  name: string;
  path: string;
  duration?: number;
  size?: number;
  format?: string;
}

export interface AnalysisStatus {
  task_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress?: number;
  phase?: string;
  message?: string;
  results?: unknown;
  error?: string;
}

export interface ClipRecommendation {
  episode_count: number;
  episode_type: 'single' | 'multi' | 'unknown';
  recommended_scheme: string;
  confidence: number;
  reasons: string[];
  alternatives: string[];
  recommended_modes: string[];
}

export interface ClipProgress {
  task_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  phase?: string;
  message: string;
}

export interface ExportProgress {
  task_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  phase?: string;
  message: string;
  output_path?: string;
}

/** 单个 AI 模型提供商的配置 */
export interface ModelProviderConfig {
  api_key: string;
  base_url?: string;
  model?: string;
  max_tokens?: number;
  temperature?: number;
  enabled: boolean;
}

/** 输出参数 */
export interface OutputConfig {
  path: string;
  quality: '720p' | '1080p' | '2k' | '4k';
  format: 'mp4' | 'mov' | 'avi';
  fps: 24 | 25 | 30 | 60;
  codec: 'h264' | 'h265' | 'vp9';
}

/** TTS（语音合成）配置 */
export interface TtsConfig {
  enabled: boolean;
  engine: 'openai' | 'edge' | 'elevenlabs' | 'fishspeech';
  voice: string;
  speed: number;
  pitch: number;
}

/** ASR（语音识别）配置 */
export interface AsrConfig {
  enabled: boolean;
  engine: 'whisper' | 'paraformer' | 'sensevoice' | 'faster_whisper';
  model: string;
  language: 'auto' | 'zh' | 'en' | 'ja';
  translate: boolean;
}

/** ViT（视觉分析）配置 */
export interface VitConfig {
  enabled: boolean;
  provider: 'openai_protocol' | 'anthropic_protocol';
  model: string;
  batch_size: number;
}


/** 硬件加速配置 */
export interface HardwareConfig {
  enabled: boolean;
  ffmpeg_hwaccel: 'auto' | 'cuda' | 'dxva2' | 'qsv' | 'videotoolbox' | 'none';
  gpu_device: string;
  threads: number;
  max_workers: number;
}

/** 完整的应用设置 */
export interface AppSettings {
  // LLM 协议
  openai_protocol: ModelProviderConfig;
  anthropic_protocol: ModelProviderConfig;
  // 功能模块
  tts: TtsConfig;
  asr: AsrConfig;
  vit: VitConfig;
  // 输出与硬件
  output: OutputConfig;
  hardware: HardwareConfig;
}
