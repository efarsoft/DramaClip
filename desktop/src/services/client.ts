/** 渲染层唯一 IPC 出口（docs/desktop/01 §4）。组件禁止直接调 window.dramaclip。 */
import type {
  AnalysisJobStatus,
  CopyFilesResult,
  EngineConfig,
  StyleInfo,
  WorkItem as WorksItem,
  ModelInfo,
  AnalysisResults,
  DashboardSummary,
  DramaClipBridge,
  DataPaths,
  ExportJob,
  ExportSubmitResult,
  JobsListResult,
  PlanDetail,
  RevealResult,
  TitleCandidate,
  HealthResult,
  ImportInspection,
  ImportRecord,
  JobInfo,
  NarrationMode,
  NarrationPlan,
  OrphanCopy,
  PingResult,
  PlanVariantsResult,
  Project,
  ProjectGetResult,
  ScannedEpisode,
  SelftestResult,
  SelftestResults,
  ServiceEvent,
  PromptsListResult,
  RelayoutResult,
  SubtitlePresetInfo,
  TtsPreviewResult,
  TtsCleanReferenceResult,
  ModeRecommendation,
  VerifyReport,
} from '@dramaclip/protocol';

function bridge(): DramaClipBridge {
  return window.dramaclip;
}

export function rpc<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
  return bridge().rpc(method, params) as Promise<T>;
}

export function appVersion(): Promise<string> {
  return bridge().appVersion();
}

export function appPaths(): Promise<DataPaths> {
  return bridge().appPaths();
}

export function restartService(): Promise<void> {
  return bridge().restartService();
}

export function pickFolder(): Promise<string | null> {
  return bridge().pickFolder();
}

export function pickAudioFile(): Promise<string | null> {
  return bridge().pickAudioFile();
}

export function revealInFolder(path: string): Promise<RevealResult> {
  return bridge().revealInFolder(path);
}

/** 复制文件到指定目录（成品库批量「复制到…」）；同名不覆盖，逐文件报成败。 */
export function copyFiles(files: readonly string[], destDir: string): Promise<CopyFilesResult> {
  return bridge().copyFiles(files, destDir);
}

export function windowControl(action: 'minimize' | 'maximize-toggle' | 'close'): Promise<void> {
  return bridge().windowControl(action);
}

/** 本地媒体预览 URL（dramaclip:// 协议，主进程注册）。 */
export function mediaUrl(path: string): string {
  return `dramaclip://local/${encodeURIComponent(path)}`;
}

export function onServiceEvent(callback: (event: ServiceEvent) => void): () => void {
  return bridge().onServiceEvent(callback);
}

export const systemApi = {
  ping: (): Promise<PingResult> => rpc<PingResult>('system.ping'),
  health: (refresh = false): Promise<HealthResult> =>
    rpc<HealthResult>('system.health', refresh ? { refresh: true } : {}),
} as const;

export const projectApi = {
  create: (name: string, sourcePath: string): Promise<Project> =>
    rpc<Project>('project.create', { name, source_path: sourcePath }),
  list: (): Promise<Project[]> => rpc<Project[]>('project.list'),
  /** remaining = 服务端时间预算收手后仍缺封面的条数（旧服务无此字段，undefined 即无欠账）。 */
  ensureCovers: (): Promise<{ ok: boolean; generated: number; remaining?: number }> =>
    rpc<{ ok: boolean; generated: number; remaining?: number }>('project.ensure_covers', {}),
  reorderEpisodes: (projectId: string, episodeIds: string[]): Promise<{ ok: boolean }> =>
    rpc<{ ok: boolean }>('project.reorder_episodes', { project_id: projectId, episode_ids: episodeIds }),
  get: (projectId: string): Promise<ProjectGetResult> =>
    rpc<ProjectGetResult>('project.get', { project_id: projectId }),
  remove: (projectId: string): Promise<{ ok: boolean }> =>
    rpc<{ ok: boolean }>('project.delete', { project_id: projectId }),
  rename: (projectId: string, name: string): Promise<Project> =>
    rpc<Project>('project.rename', { project_id: projectId, name }),
  duplicate: (projectId: string): Promise<Project> =>
    rpc<Project>('project.duplicate', { project_id: projectId }),
  scanEpisodes: (projectId: string): Promise<ScannedEpisode[]> =>
    rpc<ScannedEpisode[]>('project.scan_episodes', { project_id: projectId }),
  /** 项目级参数覆盖（K/转写档位/风格/字幕预设）；null 值 = 恢复该项全局默认。 */
  updateSettings: (
    projectId: string,
    settings: Record<string, string | number | boolean | null>,
  ): Promise<{ project_id: string; settings: Record<string, unknown> }> =>
    rpc<{ project_id: string; settings: Record<string, unknown> }>('project.update_settings', {
      project_id: projectId,
      settings,
    }),
  dashboardSummary: (): Promise<DashboardSummary> => rpc<DashboardSummary>('project.dashboard_summary'),
} as const;

export const analysisApi = {
  start: (projectId: string, episodeIds?: readonly string[]): Promise<{ job_id: string }> =>
    rpc<{ job_id: string }>(
      'analysis.start',
      episodeIds ? { project_id: projectId, episode_ids: episodeIds } : { project_id: projectId },
    ),
  status: (jobId: string): Promise<AnalysisJobStatus> =>
    rpc<AnalysisJobStatus>('analysis.status', { job_id: jobId }),
  cancel: (jobId: string): Promise<{ ok: boolean }> =>
    rpc<{ ok: boolean }>('analysis.cancel', { job_id: jobId }),
  resyncSemantic: (projectId: string, episodeId: string): Promise<{ job_id: string }> =>
    rpc<{ job_id: string }>('analysis.resync_semantic', {
      project_id: projectId,
      episode_id: episodeId,
    }),
  results: (projectId: string): Promise<AnalysisResults> =>
    rpc<AnalysisResults>('analysis.results', { project_id: projectId }),
  /** 轻量预筛（转写档位「仅推荐集精转」的执行体）；thenAnalyze=预筛完自动精转推荐集。 */
  prescreen: (projectId: string, thenAnalyze?: boolean): Promise<{ job_id: string }> =>
    rpc<{ job_id: string }>(
      'analysis.prescreen',
      thenAnalyze === true
        ? { project_id: projectId, then_analyze: true }
        : { project_id: projectId },
    ),
} as const;

/** 作品库筛选（09-10 #30「筛选·自检通过」）；'all' 只在界面层存在，不发服务端。 */
export type WorksFilter = 'passed' | 'failed' | 'partial' | 'unchecked';

/** 作品库：跨项目已完成成片。 */
export function listWorks(limit = 60, state?: WorksFilter): Promise<WorksItem[]> {
  return rpc<WorksItem[]>('export.list_works', state === undefined ? { limit } : { limit, state });
}

export const narrationApi = {
  /** 阶段①：AI 模式推荐（随项目缓存；refresh=true 忽略缓存重算）。 */
  recommendModes: (projectId: string, refresh = false): Promise<ModeRecommendation> =>
    rpc<ModeRecommendation>('narration.recommend_modes', { project_id: projectId, refresh }),
  /** 阶段③：为选中模式各产出 K 条角度互异的方案，只规划不渲染。 */
  planVariants: (
    projectId: string,
    modes: NarrationMode[],
    k?: number,
    excludePlanIds?: string[],
  ): Promise<PlanVariantsResult> =>
    rpc<PlanVariantsResult>(
      'narration.plan_variants',
      excludePlanIds
        ? { project_id: projectId, modes, k, exclude_plan_ids: excludePlanIds }
        : { project_id: projectId, modes, k },
    ),
  listStyles: (): Promise<StyleInfo[]> => rpc<StyleInfo[]>('narration.list_styles', {}),
  getPlan: (planId: string): Promise<PlanDetail> =>
    rpc<PlanDetail>('narration.get_plan', { plan_id: planId }),
  /** 不给 batchId 取全项目，给了只取那一组（规划完只显示本次产物）。 */
  listPlans: (projectId: string, batchId?: string): Promise<NarrationPlan[]> =>
    rpc<NarrationPlan[]>('narration.list_plans', {
      project_id: projectId,
      ...(batchId ? { batch_id: batchId } : {}),
    }),
} as const;

export const subtitleApi = {
  /** 内封字幕预设目录（subtitle.list_presets）：设置页「字幕」分区的选项源。 */
  listPresets: (): Promise<SubtitlePresetInfo[]> =>
    rpc<SubtitlePresetInfo[]>('subtitle.list_presets', {}),
} as const;

export const exportApi = {
  submit: (planIds: string[]): Promise<ExportSubmitResult> =>
    rpc<ExportSubmitResult>('export.submit', { plan_ids: planIds }),
  retry: (exportId: string): Promise<{ job_id: string; export_id: string }> =>
    rpc<{ job_id: string; export_id: string }>('export.retry', { export_id: exportId }),
  list: (projectId: string): Promise<ExportJob[]> =>
    rpc<ExportJob[]>('export.list', { project_id: projectId }),
  ensureCovers: (limit = 200): Promise<{ ok: boolean; generated: number }> =>
    rpc<{ ok: boolean; generated: number }>('export.ensure_covers', { limit }),
  get: (exportId: string): Promise<ExportJob> =>
    rpc<ExportJob>('export.get', { export_id: exportId }),
  /** 删除成片（§3.4）：服务端把文件移入 .trash/<日期>/ 后删记录；missing=盘上已缺的文件。 */
  delete: (exportId: string): Promise<{ ok: boolean; trashed: string[]; missing: string[] }> =>
    rpc<{ ok: boolean; trashed: string[]; missing: string[] }>('export.delete', { export_id: exportId }),
  /** 历史成片补测四项自检（job 化）；给 exportIds 则重测指定条目。 */
  selfcheck: (
    exportIds?: string[],
    limit?: number,
  ): Promise<{ ok: boolean; job_id: string | null; queued: number }> =>
    rpc<{ ok: boolean; job_id: string | null; queued: number }>(
      'export.selfcheck',
      exportIds === undefined
        ? limit === undefined ? {} : { limit }
        : { export_ids: exportIds },
    ),
} as const;

export const titlesApi = {
  generate: (planId: string): Promise<{ titles: TitleCandidate[] }> =>
    rpc<{ titles: TitleCandidate[] }>('narration.generate_titles', { plan_id: planId }),
  update: (planId: string, titles: TitleCandidate[]): Promise<{ titles: TitleCandidate[] }> =>
    rpc<{ titles: TitleCandidate[] }>('narration.update_titles', { plan_id: planId, titles }),
} as const;

export const runtimeApi = {
  status: (): Promise<{ cublas: boolean; cudnn: boolean; installed: boolean }> =>
    rpc<{ cublas: boolean; cudnn: boolean; installed: boolean }>('models.runtime_status', {}),
  install: (): Promise<{ job_id: string }> =>
    rpc<{ job_id: string }>('models.install_runtime', {}),
} as const;

/** IndexTTS 运行环境（隔离 venv）：状态/一键安装（作业模式有进度）。 */
export const indexttsApi = {
  status: (): Promise<{ installed: boolean; dir: string }> =>
    rpc<{ installed: boolean; dir: string }>('models.indextts_status', {}),
  install: (): Promise<{ job_id: string }> =>
    rpc<{ job_id: string }>('models.install_indextts', {}),
} as const;

/** models.import_records 的返回：登记本 + 读坏了的原因原文——坏了不等于空。 */
export interface ImportRecordsResult {
  readonly records: ImportRecord[];
  readonly error: string;
}

export const modelsApi = {
  list: (): Promise<ModelInfo[]> => rpc<ModelInfo[]>('models.list'),
  download: (modelId: string, source?: string, force?: boolean): Promise<{ job_id: string }> => {
    const params: Record<string, unknown> = { model_id: modelId };
    if (source !== undefined) params.source = source;
    if (force === true) params.force = true;
    return rpc<{ job_id: string }>('models.download', params);
  },
  /** 清理中断残留（*.incomplete）：删除范围与体检「中断残留」判据同一条，不碰已完成权重。 */
  cleanResidue: (modelId: string): Promise<{ removed: number; freed_bytes: number }> =>
    rpc<{ removed: number; freed_bytes: number }>('models.clean_residue', { model_id: modelId }),
  /** 登记路径外的同名多余副本（只读）：确认弹窗要展示全路径与实占体积再让删。 */
  orphanList: (modelId: string): Promise<OrphanCopy[]> =>
    rpc<OrphanCopy[]>('models.orphan_list', { model_id: modelId }),
  /** 删除一条多余副本：只接受 orphanList/体检 paths 白名单内的路径，名单外服务端拒绝。 */
  cleanOrphan: (modelId: string, path: string): Promise<{ ok: boolean; removed: string; freed_bytes: number }> =>
    rpc<{ ok: boolean; removed: string; freed_bytes: number }>('models.clean_orphan', { model_id: modelId, path }),
  /** 资产体检：给 id 报那一项，不给则批量报所有已落盘的（只读，不改文件）。 */
  verify: (modelId?: string): Promise<VerifyReport[]> =>
    rpc<VerifyReport[]>('models.verify', modelId === undefined ? {} : { model_id: modelId }),
  /** whisper 存量 snapshots/main 就地迁移成提交号布局：零重新下载；失败原因在域错误原文里。 */
  relayout: (modelId: string): Promise<RelayoutResult> =>
    rpc<RelayoutResult>('models.relayout', { model_id: modelId }),
  remove: (modelId: string): Promise<{ ok: boolean }> =>
    rpc<{ ok: boolean }>('models.delete', { model_id: modelId }),
  /** 导入向导第 ② 步：只读识别与体检，不落盘也不写登记。 */
  inspectImport: (path: string): Promise<ImportInspection> =>
    rpc<ImportInspection>('models.import_inspect', { path }),
  /** 第 ③ 步：GB 级复制是长活，走作业；进度与收尾看 jobs.get。 */
  commitImport: (payload: Record<string, string | boolean>): Promise<{ job_id: string }> =>
    rpc<{ job_id: string }>('models.import_commit', payload),
  /** 「本地导入」登记本：清单外的资产只在这里，不占资产库的内置行。 */
  importRecords: (): Promise<ImportRecordsResult> => rpc<ImportRecordsResult>('models.import_records'),
  /** 撤销一条外部登记：业主自己的文件一个字节都不动。 */
  forgetImport: (path: string): Promise<{ ok: boolean; path: string }> =>
    rpc<{ ok: boolean; path: string }>('models.import_forget', { path }),
} as const;

/** 配音试听：服务端合成一句短句并回本机路径，播放走 mediaUrl。 */
export const ttsApi = {
  preview: (engine: string, voice: string): Promise<TtsPreviewResult> =>
    rpc<TtsPreviewResult>('tts.preview', { engine, voice }),
  cleanReference: (path: string, mode: 'separate' | 'fast' = 'separate'): Promise<TtsCleanReferenceResult> =>
    rpc<TtsCleanReferenceResult>('tts.clean_reference', { path, mode }),
} as const;

/** 能力层自检（§10.3）：校验=文件层，自检=能力层，两者都过才叫 ready。 */
export const enginesApi = {
  /** 本地资产给 modelId，云端域给 domain；同步 RPC，ASR 在 CPU 上可能十几秒。 */
  selftest: (target: { modelId?: string; domain?: string }): Promise<SelftestResult> =>
    rpc<SelftestResult>(
      'engines.selftest',
      target.modelId !== undefined ? { model_id: target.modelId } : { domain: target.domain ?? '' },
    ),
  /** 历史自检账本：就绪口径的能力层那一半，重启不丢。 */
  selftestResults: (): Promise<SelftestResults> =>
    rpc<SelftestResults>('engines.selftest_results'),
} as const;

export const jobsApi = {
  list: (limit: number, activeOnly = false): Promise<JobsListResult> =>
    rpc<JobsListResult>('jobs.list', activeOnly ? { limit, active_only: true } : { limit }),
  /** 单只作业的当下状态：导入这类长活的收尾只有作业自己知道。 */
  get: (jobId: string): Promise<{ job: JobInfo }> => rpc<{ job: JobInfo }>('jobs.get', { job_id: jobId }),
  cancel: (jobId: string): Promise<{ job_id: string; cancelling: boolean; reason?: string }> =>
    rpc<{ job_id: string; cancelling: boolean; reason?: string }>('jobs.cancel', { job_id: jobId }),
  /** 清空已结束（完成/失败/取消）的任务记录；在跑与排队中的不动。 */
  clearFinished: (): Promise<{ deleted: number }> => rpc<{ deleted: number }>('jobs.clear_finished', {}),
} as const;

export const settingsApi = {
  get: (): Promise<Record<string, string>> => rpc<Record<string, string>>('settings.get'),
  update: (values: Record<string, string>): Promise<{ ok: boolean }> =>
    rpc<{ ok: boolean }>('settings.update', { values }),
} as const;

/** 可编辑 LLM 提示词（覆盖存 settings，重置回代码默认）。 */
export const promptsApi = {
  list: (): Promise<PromptsListResult> => rpc<PromptsListResult>('prompts.list'),
  save: (key: string, text: string): Promise<{ ok: boolean }> =>
    rpc<{ ok: boolean }>('prompts.save', { key, text }),
  reset: (key: string): Promise<{ ok: boolean }> => rpc<{ ok: boolean }>('prompts.reset', { key }),
} as const;

/** 引擎配置（云端/服务端点多实例，单启用）。 */
export const engineConfigsApi = {
  list: (domain: string): Promise<{ configs: EngineConfig[] }> =>
    rpc<{ configs: EngineConfig[] }>('engine_configs.list', { domain }),
  create: (input: {
    domain: string;
    name: string;
    base_url: string;
    api_key: string;
    model: string;
    enable?: boolean;
  }): Promise<EngineConfig> => rpc<EngineConfig>('engine_configs.create', input),
  update: (input: {
    id: string;
    name: string;
    base_url: string;
    api_key: string;
    model: string;
  }): Promise<EngineConfig> => rpc<EngineConfig>('engine_configs.update', input),
  remove: (id: string): Promise<{ ok: boolean }> =>
    rpc<{ ok: boolean }>('engine_configs.delete', { id }),
  enable: (id: string): Promise<EngineConfig> =>
    rpc<EngineConfig>('engine_configs.enable', { id }),
  test: (input: {
    base_url: string;
    api_key: string;
    model: string;
  }): Promise<{ ok: boolean; latency_s?: number; error?: string }> =>
    rpc('engine_configs.test', input),
} as const;
