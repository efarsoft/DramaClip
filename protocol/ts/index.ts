/**
 * DramaClip RPC 协议类型（TS 侧）。
 *
 * 唯一真相源是 ../schemas/*.json —— 任何变更先改 schema 再同步本文件
 * （CI 契约测试校验 METHOD_NAMES 与 schema x-methods 集合相等）。
 * 规范全文：docs/03-IPC协议规范.md
 */

export type JsonRpcVersion = '2.0';

export interface RpcError {
  readonly code: number;
  readonly message: string;
  readonly data?: unknown;
}

export type MethodName = (typeof METHOD_NAMES)[number];

export interface RpcRequest {
  readonly jsonrpc: JsonRpcVersion;
  readonly id: string;
  readonly method: MethodName;
  readonly params?: Readonly<Record<string, unknown>>;
}

export interface RpcResponse {
  readonly jsonrpc: JsonRpcVersion;
  readonly id: string | null;
  readonly result?: unknown;
  readonly error?: RpcError;
}

export type NotificationName = (typeof NOTIFICATION_NAMES)[number];

export interface RpcNotification {
  readonly jsonrpc: JsonRpcVersion;
  readonly method: NotificationName;
  readonly params?: Readonly<Record<string, unknown>>;
}

/** system.ping 返回体 */
export interface PingResult {
  readonly service_version: string;
  readonly protocol_version: number;
}

/** system.health 返回体（扩展字段按需出现） */
export interface HealthResult {
  readonly status: string;
  readonly uptime_s: number;
  readonly gpu?: string;
  readonly vram_free_mb?: number;
  readonly disk_free_gb?: number;
  readonly models_ok?: boolean;
}

/** ---- project 命名空间 ---- */

export interface Project {
  readonly id: string;
  readonly name: string;
  readonly source_path: string;
  readonly status: string;
  readonly created_at: number;
  readonly episode_count: number;
}

export interface Episode {
  readonly id: string;
  readonly episode_number: number;
  readonly name: string;
  readonly source_path: string;
  readonly duration?: number;
  readonly status: string;
}

export interface ScannedEpisode {
  readonly episode_number: number;
  readonly name: string;
  readonly source_path: string;
  readonly duration: number;
  readonly size_bytes: number;
}

export interface ProjectGetResult {
  readonly project: Project;
  readonly episodes: Episode[];
}

/** ---- analysis 命名空间（W2）---- */

export interface AsrSegment {
  readonly start: number;
  readonly end: number;
  readonly text: string;
  readonly speaker?: string;
  readonly emotion?: string;
}

export interface EpisodeAnalysisResult {
  readonly episode_id: string;
  readonly episode_number: number;
  readonly status: string;
  readonly asr_segment_count: number;
  readonly scene_count: number;
  readonly error?: string;
}

export interface AnalysisJobStatus {
  readonly job_id: string;
  readonly status: string;
  readonly progress: number;
  readonly message?: string;
  readonly error?: string;
  readonly episodes?: ReadonlyArray<{ episode_id: string; status: string }>;
}

export interface AnalysisResults {
  readonly episodes: EpisodeAnalysisResult[];
  readonly asr_segments?: Readonly<Record<string, AsrSegment[]>>;
}

/** 主进程 → 渲染层事件（service:event 通道） */
export type ServiceEvent =
  | { readonly type: 'service-state'; readonly state: ServiceState }
  | {
      readonly type: 'notification';
      readonly method: NotificationName;
      readonly params: Record<string, unknown>;
    };

export type ServiceState = 'starting' | 'ready' | 'restarting' | 'unavailable';

/**
 * preload 暴露给渲染层的桥接 API 形状（window.dramaclip）。
 * 单一定义：preload 用 satisfies 校验实现，渲染层据此消费。
 */
export interface DramaClipBridge {
  rpc(method: string, params?: Record<string, unknown>): Promise<unknown>;
  appVersion(): Promise<string>;
  restartService(): Promise<void>;
  onServiceEvent(callback: (event: ServiceEvent) => void): () => void;
}

export const METHOD_NAMES = [
  'system.ping',
  'system.health',
  'system.shutdown',
  'project.create',
  'project.list',
  'project.get',
  'project.delete',
  'project.scan_episodes',
  'analysis.start',
  'analysis.status',
  'analysis.cancel',
  'analysis.results',
] as const;

export const NOTIFICATION_NAMES = ['progress.update', 'log.append', 'models.download_progress'] as const;

export const PROTOCOL_VERSION = 1;
