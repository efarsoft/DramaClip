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
      try {
        const response = await window.electronAPI.backend.call<T>(method, params);
        if (!response.success) {
          const error = response.error;
          const message = error?.message || 'Unknown error';
          const code = error?.code || -32000;
          throw new IpcException(code, message, error?.data);
        }
        return response.data as T;
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        console.warn(`[IpcClient] Backend call failed (${message}), falling back to dev API: ${method}`);
        return devApiFallback.call<T>(method, params);
      }
    }
    // Dev mode fallback
    return devApiFallback.call<T>(method, params);
  }
  /**
   * 检查后端是否就绪
   */

  /**
   * 检查后端是否就绪
   */
  isBackendReady(): boolean {
    return !!window.electronAPI;
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

// Dev mode fallback when Electron API is not available
export class DevApiFallback {
  private mockProjects: Project[] = [
    { id: 'mock-1', name: '测试项目1', path: 'C:\\Projects\\test1', created_at: '2025-01-01T00:00:00', updated_at: '2025-01-02T00:00:00', episode_count: 3, status: 'ready' },
    { id: 'mock-2', name: '测试项目2', path: 'C:\\Projects\\test2', created_at: '2025-02-01T00:00:00', updated_at: '2025-02-02T00:00:00', episode_count: 5, status: 'idle' },
  ];

  private mockVideos: Episode[] = [
    { id: 'v-1', name: '第一集.mp4', path: 'C:\\Videos\\ep1.mp4', duration: 3600, size: 1500000000, format: 'mp4' },
    { id: 'v-2', name: '第二集.mp4', path: 'C:\\Videos\\ep2.mp4', duration: 4200, size: 1800000000, format: 'mp4' },
  ];

  // 分析任务模拟状态
  private analyzeTasks: Record<string, {
    status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
    progress: number;
    message?: string;
    startedAt: number;
  }> = {};

  // 剪辑/导出任务模拟状态
  private jobTasks: Record<string, {
    status: 'pending' | 'running' | 'completed' | 'failed';
    progress: number;
    phase: string;
    message?: string;
    startedAt: number;
    outputPath?: string;
  }> = {};

  // 模拟设置
  private mockSettings: AppSettings = {
    openai_protocol: { api_key: 'sk-mock-openai-key-12345', base_url: '', model: 'gpt-4o', max_tokens: 4096, temperature: 0.7, enabled: true },
    anthropic_protocol: { api_key: 'sk-ant-mock-claude-key', base_url: '', model: 'claude-3-5-sonnet-latest', max_tokens: 4096, temperature: 0.7, enabled: false },
    tts: { enabled: true, engine: 'openai', voice: 'nova', speed: 1.0, pitch: 1.0 },
    asr: { enabled: true, engine: 'whisper', model: 'large-v3', language: 'auto', translate: false },
    vit: { enabled: true, provider: 'qwen' as any, model: 'qwen-vl-max', batch_size: 4 },
    translator: { enabled: true, provider: 'deepseek' as any, source_lang: 'zh', target_lang: 'en' },
    output: { path: 'C:\\DramaClip\\Outputs', quality: '1080p', format: 'mp4', fps: 30, codec: 'h264' },
    hardware: { enabled: true, ffmpeg_hwaccel: 'auto', gpu_device: '0', threads: 4 },
  };

  private autoCompleteAnalyzeTask(taskId: string): void {
    const task = this.analyzeTasks[taskId];
    if (!task) return;

    // 模拟进度递增
    const interval = setInterval(() => {
      if (!this.analyzeTasks[taskId]) { clearInterval(interval); return; }
      task.progress = Math.min(task.progress + Math.random() * 15, 100);
      if (this.analyzeTasks[taskId].status === 'cancelled') {
        clearInterval(interval);
        return;
      }
    }, 500);

    // 3 秒后自动完成
    setTimeout(() => {
      if (this.analyzeTasks[taskId]) {
        this.analyzeTasks[taskId].status = 'completed';
        this.analyzeTasks[taskId].progress = 100;
        this.analyzeTasks[taskId].message = '分析完成';
      }
      clearInterval(interval);
    }, 3000);
  }

  isAvailable(): boolean { return true; }
  init(): void { console.log('[DevFallback] Mock API ready'); }
  onProgress(): () => void { return () => {}; }
  onLog(): () => void { return () => {}; }

  async call<T>(method: string, params?: Record<string, unknown>): Promise<T> {
    console.log(`[DevFallback] call: ${method}`, params);
    await new Promise(r => setTimeout(r, 200)); // simulate latency

    switch (method) {
      // ── 项目相关 ──
      case 'project.list':
        return [...this.mockProjects] as T;
      case 'project.create': {
        const name = params?.name as string;
        const path = params?.path as string;
        const newProject: Project = {
          id: `mock-${Date.now()}`,
          name,
          path: path || `C:\\Projects\\${name}`,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          episode_count: 0,
          status: 'idle',
        };
        this.mockProjects.unshift(newProject);
        return newProject as T;
      }
      case 'project.open': {
        const pid = params?.project_id as string;
        const p = this.mockProjects.find(x => x.id === pid);
        if (!p) throw new Error('Project not found');
        return p as T;
      }
      case 'project.delete': {
        const pid = params?.project_id as string;
        this.mockProjects = this.mockProjects.filter(x => x.id !== pid);
        return { success: true } as T;
      }
      case 'project.rename': {
        const pid = params?.project_id as string;
        const newName = params?.new_name as string;
        const project = this.mockProjects.find(x => x.id === pid);
        if (!project) throw new Error('Project not found');
        project.name = newName;
        return { ...project } as T;
      }
      case 'project.importVideos':
        return this.mockVideos as T;
      case 'project.getVideos':
        return this.mockVideos as T;

      // ── 分析相关 ──
      case 'analyze.start': {
        const pid = params?.project_id as string;
        const episodeIds = params?.episode_ids as string[];
        const taskId = `analyze-${Date.now()}`;
        this.analyzeTasks[taskId] = {
          status: 'pending',
          progress: 0,
          startedAt: Date.now(),
        };
        // 100ms 后转为 running
        setTimeout(() => {
          if (this.analyzeTasks[taskId]) {
            this.analyzeTasks[taskId].status = 'running';
            this.analyzeTasks[taskId].message = '正在执行视频分析...';
          }
        }, 100);
        // 启动自动完成流程
        this.autoCompleteAnalyzeTask(taskId);
        return { task_id: taskId } as T;
      }
      case 'analyze.getStatus': {
        const taskId = params?.task_id as string;
        const task = this.analyzeTasks[taskId];
        if (!task) {
          return {
            task_id: taskId,
            status: 'pending',
            progress: 0,
            message: '未知任务',
          } as T;
        }
        return {
          task_id: taskId,
          status: task.status,
          progress: task.progress,
          message: task.message || '等待中...',
        } as T;
      }
      case 'analyze.cancel': {
        const taskId = params?.task_id as string;
        const task = this.analyzeTasks[taskId];
        if (task) {
          task.status = 'cancelled';
          task.message = '已取消';
        }
        return { success: true } as T;
      }

      // ── 剪辑相关 ──
      case 'clip.recommend': {
        const recommendation: ClipRecommendation = {
          recommended_scheme: 'highlight',
          confidence: 0.87,
          reasons: [
            '检测到多个高潮片段',
            '用户互动数据良好',
            '内容传播潜力大',
          ],
          alternatives: ['transition', 'narration'],
        };
        return recommendation as T;
      }
      case 'clip.execute': {
        const taskId = `clip-${Date.now()}`;
        this.jobTasks[taskId] = {
          status: 'pending',
          progress: 0,
          phase: '初始化',
          startedAt: Date.now(),
        };
        // 模拟进度
        setTimeout(() => {
          if (this.jobTasks[taskId]) {
            this.jobTasks[taskId].status = 'running';
            this.jobTasks[taskId].phase = '正在分析视频...';
          }
        }, 200);
        setTimeout(() => {
          if (this.jobTasks[taskId]) {
            this.jobTasks[taskId].progress = 40;
            this.jobTasks[taskId].phase = '正在生成推荐方案...';
          }
        }, 1500);
        setTimeout(() => {
          if (this.jobTasks[taskId]) {
            this.jobTasks[taskId].progress = 80;
            this.jobTasks[taskId].phase = '正在执行剪辑...';
          }
        }, 3000);
        setTimeout(() => {
          if (this.jobTasks[taskId]) {
            this.jobTasks[taskId].status = 'completed';
            this.jobTasks[taskId].progress = 100;
            this.jobTasks[taskId].phase = '剪辑完成';
          }
        }, 5000);
        return { task_id: taskId } as T;
      }
      case 'clip.getProgress': {
        const taskId = params?.task_id as string;
        const task = this.jobTasks[taskId];
        if (!task) {
          return {
            task_id: taskId,
            status: 'pending',
            progress: 0,
            phase: '',
            message: '未知任务',
          } as T;
        }
        return {
          task_id: taskId,
          status: task.status,
          progress: task.progress,
          phase: task.phase,
          message: task.phase,
        } as T;
      }
      case 'clip.preview':
        return { preview_url: `/preview/${Date.now()}.html` } as T;

      // ── 导出相关 ──
      case 'export.start': {
        const taskId = `export-${Date.now()}`;
        this.jobTasks[taskId] = {
          status: 'pending',
          progress: 0,
          phase: '准备导出',
          startedAt: Date.now(),
        };
        // 模拟进度
        setTimeout(() => {
          if (this.jobTasks[taskId]) {
            this.jobTasks[taskId].status = 'running';
            this.jobTasks[taskId].phase = '正在编码视频...';
          }
        }, 200);
        setTimeout(() => {
          if (this.jobTasks[taskId]) {
            this.jobTasks[taskId].progress = 50;
            this.jobTasks[taskId].phase = '正在编码视频...';
          }
        }, 3000);
        setTimeout(() => {
          if (this.jobTasks[taskId]) {
            this.jobTasks[taskId].progress = 90;
            this.jobTasks[taskId].phase = '正在合并音频...';
          }
        }, 6000);
        setTimeout(() => {
          if (this.jobTasks[taskId]) {
            this.jobTasks[taskId].status = 'completed';
            this.jobTasks[taskId].progress = 100;
            this.jobTasks[taskId].phase = '导出完成';
            this.jobTasks[taskId].outputPath = 'C:\\DramaClip\\Outputs\\export_' + Date.now() + '.mp4';
          }
        }, 8000);
        return { task_id: taskId } as T;
      }
      case 'export.getProgress': {
        const taskId = params?.task_id as string;
        const task = this.jobTasks[taskId];
        if (!task) {
          return {
            task_id: taskId,
            status: 'pending',
            progress: 0,
            phase: '',
            message: '未知任务',
            output_path: '',
          } as T;
        }
        return {
          task_id: taskId,
          status: task.status,
          progress: task.progress,
          phase: task.phase,
          message: task.phase,
          output_path: (task as Record<string, unknown>).outputPath || '',
        } as T;
      }

      // ── 设置相关 ──
      case 'settings.get':
        return { ...this.mockSettings } as T;
      case 'settings.update': {
        if (params) {
          Object.assign(this.mockSettings, params);
        }
        return { success: true } as T;
      }

      // ── 系统相关 ──
      case 'system.getVersion':
        return { version: '1.0.0-dev', name: 'DramaClip' } as T;
      case 'system.getFFmpegInfo':
        return { available: true, version: '6.0', hwaccel: 'nvenc' } as T;
      case 'system.ping':
        return { pong: true } as T;

      default:
        console.warn(`[DevFallback] Unhandled method: ${method}`);
        return null as T;
    }
  }
}

export const devApiFallback = new DevApiFallback();

// ============================================================================
// 类型定义
// ============================================================================

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
  recommended_scheme: 'highlight' | 'transition' | 'narration';
  confidence: number;
  reasons: string[];
  alternatives: string[];
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

/** 翻译配置 */
export interface TranslatorConfig {
  enabled: boolean;
  provider: 'openai_protocol' | 'anthropic_protocol';
  source_lang: string;
  target_lang: string;
}

/** 硬件加速配置 */
export interface HardwareConfig {
  enabled: boolean;
  ffmpeg_hwaccel: 'auto' | 'cuda' | 'dxva2' | 'qsv' | 'videotoolbox' | 'none';
  gpu_device: string;
  threads: number;
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
  translator: TranslatorConfig;
  // 输出与硬件
  output: OutputConfig;
  hardware: HardwareConfig;
}
