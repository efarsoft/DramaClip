/**
 * IPC 通信客户端
 * 封装 ipcRenderer.invoke，提供类型安全的 API 调用
 */

import type { ElectronAPI, ProgressPayload } from '../../main/preload';
import type { IpcError } from '../types/ipc';

/**
 * 将本地文件路径转换为可在渲染进程中访问的 URL
 * 使用 dramaclip:// 自定义协议
 */
export function videoUrl(filePath: string): string {
  return `dramaclip://local/${encodeURIComponent(filePath)}`;
}

// ============================================================================
// 类型定义
// ============================================================================

export interface IpcResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: IpcError;
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
   * 执行后端调用（带超时支持）
   * @param method RPC 方法名
   * @param params 参数
   * @param options 调用选项
   */
  async call<T = unknown>(
    method: string,
    params?: Record<string, unknown>,
    options: { timeout?: number; retries?: number } = {}
  ): Promise<T> {
    const { timeout = 60000, retries = 0 } = options;  // 默认 60 秒超时

    console.debug(`[IPC] 调用 ${method}`, params ?? {});

    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        if (window.electronAPI) {
          // 使用 Promise.race 实现超时
          const timeoutPromise = new Promise<never>((_, reject) => {
            const timerId = setTimeout(() => {
              reject(new IpcException(-32004, `调用 ${method} 超时 (${timeout}ms)`));
            }, timeout);
            // 清理定时器
            setTimeout(() => clearTimeout(timerId), timeout + 100);
          });

          const response = await Promise.race([
            window.electronAPI.backend.call<T>(method, params),
            timeoutPromise,
          ]);

          if (!response.success) {
            const error = response.error;
            const message = error?.message || 'Unknown error';
            const code = error?.code || -32000;
            console.error(`[IPC] 调用 ${method} 失败`, { code, message, data: error?.data });
            throw new IpcException(code, message, error?.data);
          }

          console.debug(`[IPC] ${method} 成功`);
          return response.data as T;
        }

        console.warn(`[IPC] 后端不可用 (开发模式)`);
        throw new IpcException(-32000, 'No backend available in dev mode');

      } catch (err) {
        if (err instanceof IpcException) {
          // IpcException 可能是超时，此时可以重试
          if (attempt < retries && err.code === -32004) {
            console.warn(`[IPC] ${method} 超时，第 ${attempt + 1} 次重试...`);
            await new Promise(r => setTimeout(r, 1000 * (attempt + 1)));
            continue;
          }
          throw err;
        }

        // 其他错误
        if (attempt < retries) {
          console.warn(`[IPC] ${method} 失败 (${attempt + 1}/${retries}):`, err);
          await new Promise(r => setTimeout(r, 1000 * (attempt + 1)));
          continue;
        }

        console.error(`[IPC] ${method} 发生未知错误`, err);
        throw new IpcException(-32001, `调用 ${method} 异常: ${err instanceof Error ? err.message : String(err)}`);
      }
    }

    // 不应到达这里
    throw new IpcException(-32001, 'Unreachable');
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
  delete: (projectId: string, keepFiles?: boolean) =>
    ipcClient.call<{ success: boolean }>('project.delete', { project_id: projectId, keep_files: keepFiles }),
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
  /** 停止/取消正在运行的剪辑任务 */
  stop: (taskId: string) =>
    ipcClient.call<{ success: boolean; task_id?: string; message?: string }>('clip.stop', {
      task_id: taskId,
    }),
  /** 生成AI标题 */
  generateTitle: (projectId: string, count: number = 5) =>
    ipcClient.call<TitleGenerationResult>('clip.generateTitle', {
      project_id: projectId,
      count,
    }),
};

// 导出相关 API
export const exportApi = {
  /** 对 clip 任务的输出进行转码/封装导出 */
  start: (projectId: string, outputConfig: Record<string, unknown>) =>
    ipcClient.call<{ task_id: string; output_path: string }>('export.start', {
      project_id: projectId,
      output_config: outputConfig,
    }),
  getProgress: (taskId: string) =>
    ipcClient.call<ExportProgress>('export.getProgress', { task_id: taskId }),
  /** 取消正在运行的导出任务 */
  cancel: (taskId: string) =>
    ipcClient.call<{ success: boolean; task_id?: string; message?: string }>('export.cancel', {
      task_id: taskId,
    }),
};

// 设置相关 API
export const settingsApi = {
  get: () => ipcClient.call<AppSettings>('settings.get'),
  update: (settings: Partial<AppSettings>) =>
    ipcClient.call<{ success: boolean }>('settings.update', settings),
};

// 系统相关 API
export interface StorageInfo {
  outputsDir: string;
  outputsCount: number;
  outputsSize: number;
  cacheSize: number;
  tempSize: number;
  totalSize: number;
}

export const systemApi = {
  getVersion: () => ipcClient.call<{ version: string; name: string }>('system.getVersion'),
  getFFmpegInfo: () =>
    ipcClient.call<{ available: boolean; version: string; hwaccel: string }>(
      'system.getFFmpegInfo'
    ),
  getStorageInfo: () => ipcClient.call<StorageInfo>('system.getStorageInfo'),
  ping: () => ipcClient.call<{ pong: boolean }>('system.ping', { timestamp: Date.now() }),
};

// 小工具相关 API
export interface TranscribeSegment {
  id: string;
  text: string;
  start: number;
  end: number;
  speaker?: string;
}

export interface TranscribeResult {
  segments: TranscribeSegment[];
  prose: string;
}

export interface TranscribeTaskStatus {
  task_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  message: string;
  results?: TranscribeResult;
  error?: string;
}

export const toolsApi = {
  transcribe: (videoPath: string, mode: 'fast' | 'precise') =>
    ipcClient.call<{ task_id: string; status: string }>('tools.transcribe', {
      video_path: videoPath,
      mode,
    }),
  getProgress: (taskId: string) =>
    ipcClient.call<TranscribeTaskStatus>('tools.getProgress', { task_id: taskId }),
  rewrite: (script: string, promptStyle: 'shocking' | 'suspense' | 'emotional' | 'rewriter') =>
    ipcClient.call<{ rewritten: string }>('tools.rewrite', {
      script,
      prompt_style: promptStyle,
    }),
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
  /** 打开项目时自动扫描目录的同步结果 */
  sync_result?: {
    found: number;
    removed: number;
    missing: number;
  };
  /** 打开时一并返回的视频列表 */
  videos?: Episode[];
}

export interface Episode {
  id: string;
  name: string;
  path: string;
  duration?: number;
  size?: number;
  format?: string;
  thumbnail_path?: string;
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

export interface GeneratedTitle {
  title: string;
  style: 'shocking' | 'suspense' | 'emotional' | 'humorous' | 'curiosity' | 'controversial';
  style_label: string;
  description: string;
  score: number;
}

export interface GeneratedIntro {
  short: string;
  medium: string;
  long: string;
  hashtags: string[];
}

export interface TitleGenerationResult {
  success: boolean;
  titles: GeneratedTitle[];
  intro: GeneratedIntro;
  platform_suggestions: string[];
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
  engine: 'openai' | 'edge' | 'elevenlabs' | 'fishspeech' | 'supertonic' | 'styletts2' | 'soulvoice' | string;
  voice: string;
  speed: number;
  pitch: number;
}

/** ASR（语音识别）配置 */
export interface AsrConfig {
  enabled: boolean;
  engine: 'whisper' | 'paraformer' | 'sensevoice' | 'faster_whisper' | string;
  model: string;
  language: 'auto' | 'zh' | 'en' | 'ja' | string;
  translate: boolean;
  enable_emotion?: boolean;
  enable_audio_events?: boolean;
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
