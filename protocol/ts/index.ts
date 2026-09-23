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
  /** 本机 ffmpeg 自述版本；空串 = 渲染引擎不可用。 */
  readonly ffmpeg_version: string;
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
  /** 源音频进仓已削顶：成片限幅只能压电平，不能把平顶长回来。 */
  readonly clipping?: boolean;
  readonly peak_dbfs?: number | null;
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
  /** 人读阶段文本（服务端字段就叫 label，见 protocol/schemas/jobs.json JobInfo）。 */
  readonly label?: string | null;
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
  /** 剧本清洗层丢掉的段数（未知集号/越界/重叠/空文案）；仅编剧链会写，其余模式为 0。 */
  readonly dropped_segments?: number;
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
  /** 过不了转化门禁时的第一条原因；ready 方案无此字段。 */
  readonly block_reason?: string;
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
  /** 内置清单里的身份；清单外的目录只在 import_records 里出现，不占这一列。 */
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
  /** 磁盘实占字节（未安装为 0）；与标称 size_label 不是一回事。 */
  readonly size_bytes?: number;
  readonly tier?: string;
  readonly speed?: number;
  readonly quality?: number;
  readonly desc?: string;
  readonly sources?: ReadonlyArray<ModelSource>;
  /** 引擎是否真接进了工厂：false = 储备资产，UI 不得当作可用能力展示。 */
  readonly engine_ready: boolean;
  /** 本地导入的登记项；null = 这份资产不是导入进来的（应用下载或手动放置）。 */
  readonly imported?: ImportRecord | null;
}

/** 资产体检单项判据（models.verify）。 */
export interface VerifyCheck {
  readonly name: string;
  /** fail = 不可用；warn = 可用但有隐患（如重复缓存、无下载清单）；skip = 前置项已 fail。 */
  readonly status: 'pass' | 'warn' | 'fail' | 'skip';
  readonly detail?: string;
  /** 修复动作的结构化白名单（如「唯一路径」warn 附带的多余副本全路径）；动作只删这里列出的路径。 */
  readonly paths?: ReadonlyArray<string>;
}

export interface VerifyReport {
  readonly model_id: string;
  readonly name: string;
  readonly kind: string;
  readonly engine: string;
  readonly engine_ready: boolean;
  readonly path?: string;
  /** 任一 check 为 fail 即 false。 */
  readonly ok: boolean;
  readonly checks: ReadonlyArray<VerifyCheck>;
}

/** whisper 存量缓存就地迁移的结果（models.relayout）。 */
export interface RelayoutResult {
  /** 迁移后（或幂等命中时既有）的快照目录绝对路径。 */
  readonly path: string;
  /** false = 已是目标布局，本次未动盘（幂等空操作）。 */
  readonly migrated: boolean;
}

/** 登记路径之外的同名多余副本（models.orphan_list 条目；models.clean_orphan 的删除白名单）。 */
export interface OrphanCopy {
  readonly path: string;
  readonly size_bytes: number;
}

/** TTS 自检顺带落盘的引擎能力快照（EngineCaps.to_dict；reason 已脱敏）。ASR/云端域不带。 */
export interface SelftestCaps {
  readonly sample_rate: number;
  readonly supports_cloning: boolean;
  readonly supports_emotion: boolean;
  readonly speed_control: 'native' | 'ssml' | 'none';
  readonly available: boolean;
  readonly reason: string;
}

/** 能力层自检结果（engines.selftest；账本值同形，多一个 at）。 */
export interface SelftestResult {
  readonly ok: boolean;
  /** 账本键：本地资产 = model_id，云端 = cloud:<domain>。 */
  readonly key?: string;
  /** 实际跑起来的引擎名（如 faster_whisper:small）。 */
  readonly engine?: string;
  /** ASR：样例识别字数。 */
  readonly chars?: number;
  readonly elapsed_s?: number;
  /** TTS：合成音频实测时长（秒）。 */
  readonly duration_s?: number;
  /** 云端域：连通延迟（engine_configs.test 透传）。 */
  readonly latency_s?: number | null;
  /** ASR：识别文本前 60 字。 */
  readonly text?: string;
  /** ok=false 时的失败原文。 */
  readonly error?: string | null;
  /** epoch 毫秒：这次自检发生在何时（落账后才有）。 */
  readonly at?: number;
  /** TTS：引擎能力快照。 */
  readonly caps?: SelftestCaps;
}

/** 自检账本（engines.selftest_results）：key → 结果。 */
export type SelftestResults = Readonly<Record<string, SelftestResult>>;

/** 本地导入登记项（models/imported.json 的一行）。 */
export interface ImportRecord {
  readonly model_id: string | null;
  /** asr | tts；外部资产由业主在第 ② 步声明。 */
  readonly kind: string;
  /** 外部资产为空：认不出身份就没有承接引擎。 */
  readonly engine?: string;
  /** 资产此刻所在的位置：copy/move 在库内 placement，register（冲突时选「并存」也算）在业主自己的目录。 */
  readonly path: string;
  /** 导入时业主挑的那个目录。 */
  readonly source_path: string;
  readonly mode: 'copy' | 'move' | 'register';
  readonly label?: string;
  /** true = 落位登记当时体检不通过（业主显式按现状导入，或仅登记了一份坏资产）。 */
  readonly incomplete: boolean;
  /** epoch 毫秒：移除时的「何时导入」提示要有据可查。 */
  readonly imported_at: number;
}

/** 导入向导第 ② 步的实测结果（models.import_inspect，只读）。 */
export interface ImportInspection {
  readonly source_path: string;
  readonly file_count: number;
  /** 实测字节数，不是清单标称值。 */
  readonly total_bytes: number;
  readonly recognized: boolean;
  readonly model_id?: string | null;
  readonly name?: string | null;
  readonly kind?: string | null;
  readonly engine?: string | null;
  readonly engine_ready: boolean;
  /** 模型真正所在的那一层（zip 解出来常带一层同名目录）。 */
  readonly model_root?: string | null;
  /** HF 缓存根；平铺目录为 null。 */
  readonly cache_path?: string | null;
  /** 凭什么认成这个模型；认不出来时说明为什么。 */
  readonly basis: string;
  readonly missing_files?: ReadonlyArray<string>;
  readonly target?: { placement: string; path: string; free_bytes: number } | null;
  /** 库里已有同一件资产；非 null 时 import_commit 必须先给 on_conflict 裁决。 */
  readonly conflict?: {
    model_id: string;
    path: string;
    size_bytes: number;
    ok: boolean;
    failed_checks?: ReadonlyArray<string>;
  } | null;
  readonly checks: ReadonlyArray<VerifyCheck>;
  /** 第 ② 步闸门：false 就不许落位（除非业主显式选不完整导入）。 */
  readonly ok: boolean;
}

/** tts.preview 返回体：产物是本机绝对路径，经 dramaclip:// 协议直接给 <audio> 播。 */
export interface TtsPreviewResult {
  readonly path: string;
  /** ffprobe 实测秒数；服务端已保证 >0，否则报错而非返回空样本。 */
  readonly duration_s: number;
  readonly engine: string;
  readonly voice: string;
  readonly text: string;
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
  pickAudioFile(): Promise<string | null>;
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
  'models.indextts_status',
  'models.install_indextts',
  'narration.generate_titles',
  'narration.update_titles',
  'export.get',
  'jobs.list',
  'jobs.get',
  'jobs.cancel',
  'subtitle.list_presets',
  'models.list',
  'models.download',
  'models.clean_residue',
  'models.clean_orphan',
  'models.orphan_list',
  'models.scan_local',
  'models.verify',
  'models.relayout',
  'models.import_inspect',
  'models.import_commit',
  'models.import_records',
  'models.import_forget',
  'models.delete',
  'engines.selftest',
  'engines.selftest_results',
  'engine_configs.list',
  'engine_configs.create',
  'engine_configs.update',
  'engine_configs.delete',
  'engine_configs.enable',
  'engine_configs.test',
  'settings.get',
  'settings.update',
  'settings.test_llm',
  'tts.preview',
  'prompts.list',
  'prompts.save',
  'prompts.reset',
] as const;

export const NOTIFICATION_NAMES = ['progress.update', 'log.append', 'models.download_progress'] as const;

export const PROTOCOL_VERSION = 1;

/** ---- prompts 命名空间（可编辑 LLM 提示词） ---- */

export interface PromptInfo {
  readonly key: string;
  readonly title: string;
  readonly description: string;
  /** 代码内置默认（重置后的值） */
  readonly default: string;
  /** 当前生效值（覆盖或默认） */
  readonly current: string;
  readonly overridden: boolean;
}

export interface PromptsListResult {
  readonly prompts: PromptInfo[];
}
