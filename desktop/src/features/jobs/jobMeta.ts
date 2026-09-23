/** 任务展示元数据：类型词 / 路由 / 主体文案 / 排序 / 时长——纯函数与常量，不发 RPC。 */
import type { JobInfo, JobStatus } from '@dramaclip/protocol';
import { isActiveJob } from '../../stores/jobs';

// 在跑判定与汇总住在 stores/jobs（StatusBar 在 components 层，禁止反向依赖 features）；
// 这里转出单一来源，features 侧调用方不必记两个地址。
export { isActiveJob, summarizeJobs, type JobsSummary } from '../../stores/jobs';

/** 线上实际会出现的全部类型（service 各 api create 调用的口径）；未知类型原样透出，不硬造中文。 */
export const JOB_TYPE_LABELS: Readonly<Record<string, string>> = {
  prescreen: '预筛',
  analysis: '分析',
  narration: '编剧',
  export: '渲染',
  export_selfcheck: '成片自检',
  semantic: '语义重对齐',
  model_download: '模型下载',
  model_import: '模型导入',
  cuda_runtime: 'CUDA 环境安装',
  indextts_runtime: '配音环境安装',
};

/** ref_id=project_id 的类型才可路由进项目；export 走成品详情路由；其余给聚合页或不可路由。 */
const PROJECT_REF_ROUTES: Readonly<Record<string, string>> = {
  analysis: 'analysis',
  prescreen: 'analysis',
  narration: 'produce',
};

/** 环境安装类任务的落点（ref 是固定串，不含项目语境）。 */
const ENGINE_TYPES: ReadonlySet<string> = new Set(['model_download', 'model_import', 'cuda_runtime', 'indextts_runtime']);

export function jobTypeLabel(type: string): string {
  return JOB_TYPE_LABELS[type] ?? type;
}

/** 「去处理」的路由；null = 该类型没有可去的界面（缺席而非假按钮）。 */
export function jobRoute(job: JobInfo): string | null {
  if (ENGINE_TYPES.has(job.type)) return '/engines';
  if (job.type === 'export' && job.ref_id !== null && job.ref_id !== '') {
    return `/works/${job.ref_id}`;
  }
  if (job.type === 'export_selfcheck') return '/works';  // 批次作业没有单条落点，去成品库看结果
  const sub = PROJECT_REF_ROUTES[job.type];
  if (sub === undefined || job.ref_id === null || job.ref_id === '') return null;
  return `/projects/${job.ref_id}/${sub}`;
}

/** 主体名册：抽屉打开时低频拉取，把 ref_id 翻译成人读名字。 */
export interface JobSubjectNames {
  readonly projects: ReadonlyMap<string, string>;
  readonly models: ReadonlyMap<string, string>;
}

export const EMPTY_NAMES: JobSubjectNames = { projects: new Map(), models: new Map() };

/** 主体文案：翻得出名字用名字，翻不出来用短 id——绝不编造。 */
export function jobSubject(job: JobInfo, names: JobSubjectNames): string {
  const ref = job.ref_id ?? '';
  if (PROJECT_REF_ROUTES[job.type] !== undefined) {
    return names.projects.get(ref) ?? `项目 ${shortId(ref)}`;
  }
  if (job.type === 'model_download') return names.models.get(ref) ?? `模型 ${shortId(ref)}`;
  if (job.type === 'model_import') return ref === '' ? '本地文件' : `导入 ${ref}`;
  if (job.type === 'cuda_runtime') return 'CUDA 运行环境';
  if (job.type === 'indextts_runtime') return 'IndexTTS 配音环境';
  if (job.type === 'export_selfcheck') return '历史成片补测';
  if (job.type === 'semantic') return '单集语义重对齐';
  return shortId(ref);
}

export function shortId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}

function pad2(value: number): string {
  return value < 10 ? `0${String(value)}` : String(value);
}

const STATUS_RANK: Readonly<Record<JobStatus, number>> = {
  failed: 0,
  running: 1,
  pending: 2,
  cancelled: 3,
  completed: 4,
};

/** 失败优先，其次在跑，终态垫底；同级按最近变更倒序（与服务端默认排序一致）。 */
export function sortJobs(jobs: readonly JobInfo[]): JobInfo[] {
  return [...jobs].sort(
    (a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status] || b.updated_at - a.updated_at,
  );
}

/** 时长文本：只用两个服务端毫秒时钟相减，不用本机时钟（跨机时区/漂移不掺和）。 */
export function durationLabel(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const days = Math.floor(total / 86_400);
  const hours = Math.floor((total % 86_400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (days > 0) return `${String(days)}天${String(hours)}时`;
  if (hours > 0) return `${String(hours)}时${pad2(minutes)}分`;
  if (minutes > 0) return `${String(minutes)}分${pad2(seconds)}秒`;
  return `${String(seconds)}秒`;
}

/** 在跑 = server_time_ms − created_at；终态 = updated_at − created_at（定格耗时）。 */
export function jobElapsedMs(job: JobInfo, serverTimeMs: number | null): number | null {
  if (serverTimeMs === null) return null;
  return isActiveJob(job) ? serverTimeMs - job.created_at : job.updated_at - job.created_at;
}
