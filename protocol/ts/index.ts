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
  readonly cover_path?: string;
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
  readonly highlight_count: number;
  readonly genre?: string;
  readonly error?: string;
}

export interface HighlightSegment {
  readonly start: number;
  readonly end: number;
  readonly score: number;
  readonly reason?: string;
}

export interface ConflictScorePoint {
  readonly scene_index: number;
  readonly start: number;
  readonly end: number;
  readonly score: number;
  readonly reason?: string;
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
  readonly highlights?: Readonly<Record<string, HighlightSegment[]>>;
  readonly conflict_scores?: Readonly<Record<string, ConflictScorePoint[]>>;
}

/** ---- narration / export 命名空间（W4）---- */

export type NarrationMode =
  | 'raw_clip'
  | 'intro_narration'
  | 'cross_narration'
  | 'full_narration'
  | 'dialogue_narration'
  | 'subtitle_flow'
  | 'ultra_short_hook'
  | 'dual_host_chat'
  | 'inner_monologue';

export interface TimelineSegment {
  readonly episode_id: string;
  readonly start: number;
  readonly end: number;
  readonly audio: 'original' | 'narration' | 'ducked';
  readonly transition?: 'cut' | 'fade' | 'black' | 'flash';
  readonly subtitle_text?: string | null;
}

export interface PlanData {
  readonly mode: NarrationMode;
  readonly timeline: TimelineSegment[];
  readonly narration_texts: ReadonlyArray<{ id: string; text: string; voice?: string; audio_path?: string; duration?: number }>;
}

export interface NarrationPlan {
  readonly id: string;
  readonly project_id: string;
  readonly narration_mode: NarrationMode;
  readonly episode_ids: string[];
  readonly plan_data: PlanData;
  readonly status: string;
  readonly created_at: number;
}

export interface ExportJob {
  readonly id: string;
  readonly project_id: string;
  readonly plan_id?: string;
  readonly narration_mode?: string;
  readonly output_path?: string;
  readonly status: string;
  readonly progress: number;
  readonly duration_s?: number;
  readonly size_bytes?: number;
  readonly error?: string;
  readonly created_at: number;
  readonly completed_at?: number;
}

/** 作品库条目（跨项目已完成成片，export.list_works）。 */
export interface WorkItem {
  readonly id: string;
  readonly project_id: string;
  readonly project_name: string;
  readonly narration_mode?: string;
  readonly output_path: string;
  readonly duration_s?: number;
  readonly size_bytes?: number;
  readonly completed_at?: number;
}

export interface ModelInfo {
  readonly model_id: string;
  readonly kind: string;
  readonly engine: string;
  readonly repo_id: string;
  readonly name: string;
  readonly required: boolean;
  readonly notes?: string;
  readonly status: string;
  readonly path?: string;
}

export interface SubtitlePresetInfo {
  readonly preset_id: string;
  readonly preset_name: string;
  readonly description: string;
}

export interface DashboardSummary {
  readonly project_count: number;
  readonly episode_count: number;
  readonly analyzed_episodes: number;
  readonly export_count: number;
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
  /** 原生目录选择；用户取消返回 null。 */
  pickFolder(): Promise<string | null>;
  /** 原生视频文件选择；用户取消返回 null。 */
  pickVideoFile(): Promise<string | null>;
  /** 在系统文件管理器中定位文件。 */
  revealInFolder(path: string): Promise<void>;
  /** 自定义标题栏窗口控制（frame:false）。 */
  windowControl(action: 'minimize' | 'maximize-toggle' | 'close'): Promise<void>;
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
  'project.rename',
  'project.duplicate',
  'project.scan_episodes',
  'project.dashboard_summary',
  'project.ensure_covers',
  'analysis.prescreen',
  'analysis.update_asr',
  'analysis.resync_semantic',
  'analysis.start',
  'analysis.status',
  'analysis.cancel',
  'analysis.results',
  'narration.generate_plans',
  'narration.list_plans',
  'narration.replace_timeline',
  'export.start',
  'export.list',
  'export.list_works',
  'subtitle.list_presets',
  'models.list',
  'models.download',
  'models.scan_local',
  'models.delete',
  'settings.get',
  'settings.update',
  'settings.test_llm',
] as const;

export const NOTIFICATION_NAMES = ['progress.update', 'log.append', 'models.download_progress'] as const;

export const PROTOCOL_VERSION = 1;
