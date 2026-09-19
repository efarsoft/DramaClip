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

/** 健康检查扩展：GPU 探测结果（未就绪时 ready=false，服务端后台补测）。 */
export interface GpuInfo {
  readonly ready: boolean;
  readonly vendor: string;
  readonly name: string;
  readonly driver_version: string;
  readonly max_cuda_version: string;
}

/** system.health 返回体（扩展字段按需出现） */
export interface HealthResult {
  readonly status: string;
  readonly uptime_s: number;
  readonly gpu?: string;
  readonly gpu_info?: GpuInfo;
  readonly vram_free_mb?: number;
  readonly disk_free_gb?: number;
  readonly ram_total_gb?: number;
  readonly ram_free_gb?: number;
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
  /** 项目级参数覆盖（方案数 K/转写档位/解说风格/字幕预设等）；空对象=全部使用全局默认。 */
  readonly settings: Record<string, unknown>;
}

export interface Episode {
  readonly id: string;
  readonly episode_number: number;
  readonly name: string;
  readonly source_path: string;
  readonly duration?: number;
  readonly status: string;
  readonly cover_path?: string;
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
  /** 文本来源：ocr_fixed=OCR 校对过；review=待人工复核；缺省=纯 ASR */
  readonly source?: string;
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

export type JobStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface JobInfo {
  readonly id: string;
  readonly type: string;
  readonly ref_id: string | null;
  readonly status: JobStatus;
  readonly progress: number;
  readonly error?: string | null;
  readonly created_at: number;
  readonly updated_at: number;
}

export interface TitleCandidate {
  readonly text: string;
  readonly selected: boolean;
}
export interface JobsListResult {
  readonly jobs: JobInfo[];
  readonly server_time_ms: number;
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
  /** 卖点角度名（界面金色标签）；无解说的模式为空串。 */
  readonly angle?: string;
  /** 模型自选这条角度的理由（规格 4.3 卡片四要素之一）。 */
  readonly angle_reason?: string;
  /** 1..K 的槽位号。 */
  readonly variant_index?: number;
  /** 与同 batch 同模式已接受兄弟方案的最大取材重叠；null=首条无兄弟。 */
  readonly overlap_max?: number | null;
  /** 一次 plan_variants 调用产出全组的标识（= 该作业 job_id）。 */
  readonly batch_id?: string | null;
}

/** 一条方案的成本账（规格 4.4 成本预估卡数据源）。 */
export interface PlanCost {
  readonly copy_llm_calls: number;
  readonly tts_calls: number;
}

/** narration.get_plan 返回体。 */
export interface PlanDetail {
  readonly plan: NarrationPlan;
  readonly cost: PlanCost;
}

/** narration.plan_variants 返回体。 */
export interface PlanVariantsResult {
  readonly job_id: string;
  readonly k: number;
  readonly batch_id: string;
}

/** export.submit 接受的一条：方案 → 导出记录 → 任务。 */
export interface ExportSubmission {
  readonly plan_id: string;
  readonly export_id: string;
  readonly job_id: string;
}

/** export.submit 拒绝的一条，带人读理由（规格 4.4 队列页逐条显示）。 */
export interface ExportRejection {
  readonly plan_id: string;
  readonly reason: string;
}

/** export.submit 返回体。 */
export interface ExportSubmitResult {
  readonly exports: readonly ExportSubmission[];
  readonly rejected: readonly ExportRejection[];
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
  /** 关联的编排方案（成片详情页据此取文案与标题）。 */
  readonly narration_plan_id?: string;
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
  /** 逐片钩帧封面（渲染完成时生成；历史成片由 export.ensure_covers 补拍）。 */
  readonly cover_path?: string;
}

/** 模型下载源（kind ∈ modelscope | hf_mirror | huggingface）。 */
export interface ModelSource {
  readonly kind: string;
  readonly web_url: string;
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
  readonly size_label?: string;
  readonly tier?: string;
  readonly speed?: number;
  readonly quality?: number;
  readonly desc?: string;
  readonly sources?: ReadonlyArray<ModelSource>;
}

/** 引擎配置（云端/服务端点多实例，单启用）。 */
export interface EngineConfig {
  readonly id: string;
  readonly domain: string;
  readonly name: string;
  readonly base_url: string;
  readonly api_key: string;
  readonly model: string;
  readonly enabled: number;
  readonly api_key_masked: string;
  readonly created_at?: number;
}

/** 解说风格库条目（narration.list_styles）。 */
export interface StyleInfo {
  readonly style_id: string;
  readonly name: string;
  readonly desc?: string;
  readonly directives: string;
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
  /** 本地数据目录锚点（关于页「本地数据」入口）。 */
  appPaths(): Promise<DataPaths>;
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

/** 本地数据目录（主进程 dataDir 锚点 + 服务端 _SUBDIRS 同名约定）。 */
export interface DataPaths {
  readonly root: string;
  readonly outputs: string;
  readonly models: string;
  readonly logs: string;
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
  'project.update_settings',
  'project.duplicate',
  'project.scan_episodes',
  'project.dashboard_summary',
  'project.ensure_covers',
  'project.reorder_episodes',
  'analysis.prescreen',
  'analysis.update_asr',
  'analysis.resync_semantic',
  'analysis.start',
  'analysis.status',
  'analysis.cancel',
  'analysis.results',
  'narration.plan_variants',
  'narration.get_plan',
  'narration.list_plans',
  'narration.list_styles',
  'export.submit',
  'export.retry',
  'export.list',
  'export.list_works',
  'export.ensure_covers',
  'models.runtime_status',
  'models.install_runtime',
  'narration.generate_titles',
  'narration.update_titles',
  'export.get',
  'jobs.list',
  'jobs.get',
  'jobs.cancel',
  'subtitle.list_presets',
  'models.list',
  'models.download',
  'models.scan_local',
  'models.delete',
  'engine_configs.list',
  'engine_configs.create',
  'engine_configs.update',
  'engine_configs.delete',
  'engine_configs.enable',
  'engine_configs.test',
  'settings.get',
  'settings.update',
  'settings.test_llm',
] as const;

export const NOTIFICATION_NAMES = ['progress.update', 'log.append', 'models.download_progress'] as const;

export const PROTOCOL_VERSION = 1;
