/** 四阶段状态与卡点文案派生（规格 09-10 §2.3 四阶段 / §3.1 四态 + 卷三意见 02/03）。
 *
 * 纯函数，不发 RPC：工作台矩阵与剧库五要素卡共用同一套词汇与判则——
 * 阶段词、卡点句式两处一致，改一处两处都变（卷三意见 07：共词汇不共组件）。
 *
 * 三个聚合字段（analyzedCount/planCount/staleHint）暂无 RPC 供数：传 null 即进
 * 「宁灰勿假绿」分支——阶段态取不到就标 unknown，绝不倒推绿灯（卷三意见 03）。
 * export 类任务的 ref_id=export_id 挂不到剧上，因此「正在导出」在剧维度看不见；
 * 成品数是硬数据，「已出片」灯不受影响（聚合 RPC 落地后补 active）。
 */
import type { JobInfo } from '@dramaclip/protocol';

export type StageKey = 'intake' | 'analysis' | 'planning' | 'export';
export type StageState = 'idle' | 'active' | 'done' | 'stale' | 'unknown';
export type StageMap = Readonly<Record<StageKey, StageState>>;

export const STAGE_ORDER: readonly StageKey[] = ['intake', 'analysis', 'planning', 'export'];

/** 阶段词表：矩阵、剧库卡、阶段条共用，不另造同义词。 */
export const STAGE_WORDS: Readonly<Record<StageKey, string>> = {
  intake: '进素材',
  analysis: '分析',
  planning: '规划',
  export: '出片',
};

const STAGE_NUMERALS: Readonly<Record<StageKey, string>> = {
  intake: '①',
  analysis: '②',
  planning: '③',
  export: '④',
};

export function stageLabel(key: StageKey): string {
  return `${STAGE_NUMERALS[key]} ${STAGE_WORDS[key]}`;
}

export interface StageFacts {
  readonly episodeCount: number;
  readonly workCount: number;
  /** 该剧在跑（pending/running）的任务类型；只收 ref_id=project_id 的类型。 */
  readonly activeTypes: ReadonlySet<string>;
  /** 最近在跑任务的人读阶段文本（线上字段 job.label）；没有则 null。 */
  readonly activeLabel: string | null;
  /** 该剧最近一条失败任务；error 保留原文不截断。 */
  readonly failed: { readonly type: string; readonly error: string } | null;
  /** 已转写集数（聚合 RPC 字段）：null = 数据源未落地，② 只亮灰。 */
  readonly analyzedCount: number | null;
  /** 方案数（聚合 RPC 字段）：null = 未落地，③ 拿成品硬证据倒推，否则灰。 */
  readonly planCount: number | null;
  /** 分析是否重跑于方案快照之后（方案已过期）：null = 无从判断。 */
  readonly staleHint: boolean | null;
  /** 任务账里是否有过完成的 analysis/prescreen——卡点兜底句区分「没跑过」与「跑过但账缺」。 */
  readonly analysisEverCompleted: boolean;
}

export function deriveStages(facts: StageFacts): StageMap {
  return {
    intake: facts.episodeCount > 0 ? 'done' : 'idle',
    analysis: deriveAnalysis(facts),
    planning: derivePlanning(facts),
    export: deriveExport(facts),
  };
}

function deriveAnalysis(facts: StageFacts): StageState {
  if (facts.activeTypes.has('analysis') || facts.activeTypes.has('prescreen')) return 'active';
  // 宁灰勿假绿：没有聚合计数时，即便有成品也不点绿——分析可能已被追加的剧集作废。
  if (facts.analyzedCount === null) return 'unknown';
  if (facts.episodeCount > 0 && facts.analyzedCount >= facts.episodeCount) return 'done';
  if (facts.analyzedCount > 0) return 'active';
  return 'idle';
}

function derivePlanning(facts: StageFacts): StageState {
  if (facts.activeTypes.has('narration')) return 'active';
  if (facts.staleHint === true) return 'stale';
  if (facts.planCount !== null) return facts.planCount > 0 ? 'done' : 'idle';
  // 成品是「规划过且渲染过」的硬证据；没有成品时方案账缺失，亮灰不猜。
  return facts.workCount > 0 ? 'done' : 'unknown';
}

function deriveExport(facts: StageFacts): StageState {
  if (facts.activeTypes.has('export')) return 'active';
  return facts.workCount > 0 ? 'done' : 'idle';
}

export function allStagesDone(stages: StageMap): boolean {
  return STAGE_ORDER.every((key) => stages[key] === 'done');
}

/** 全灰灯组：成品/任务账取不到时点它——宁灰勿假绿，卡点句同时缺席而不是编一句。 */
export const UNKNOWN_STAGES: StageMap = {
  intake: 'unknown',
  analysis: 'unknown',
  planning: 'unknown',
  export: 'unknown',
};

// ── 卡点文案（卷三意见 02：说人话、给动作，不刷状态词）────────────────

export type BlockTone = 'error' | 'warning' | 'action';

export interface BlockNote {
  /** 卡在哪个阶段：UI 用 tone 把该阶段的灯改色，其余灯照常。 */
  readonly stage: StageKey;
  readonly tone: BlockTone;
  /** 现象 + 下一步一句话；失败 error 原文进句不截断。 */
  readonly text: string;
  readonly actionLabel: string;
  readonly route: string;
}

export interface BlockContext {
  readonly dramaId: string;
  readonly createdAtMs: number;
  readonly serverTimeMs: number;
}

const DAY_MS = 86_400_000;
const STALLED_DAYS = 14;

/** 失败任务类型 → 阶段；与 todos.ts JOB_ROUTES 同口径。 */
function failedStage(type: string): StageKey {
  if (type === 'narration') return 'planning';
  if (type === 'export') return 'export';
  return 'analysis';
}

function activeStageOf(activeTypes: ReadonlySet<string>): StageKey | null {
  if (activeTypes.has('narration')) return 'planning';
  if (activeTypes.has('export')) return 'export';
  if (activeTypes.has('analysis') || activeTypes.has('prescreen')) return 'analysis';
  return null;
}

/** 阶段 → 剧空间真实路由：①② 的界面在分析页里，③④ 的界面在出片页里。 */
export function stageRoute(dramaId: string, stage: StageKey): string {
  if (stage === 'intake' || stage === 'analysis') return `/projects/${dramaId}/analysis`;
  return `/projects/${dramaId}/produce`;
}

/** 一条剧只给一条卡点：按「失败 > 过期 > 没喂料 > 正在跑 > 停滞 > 没开跑」取最重的一条。 */
export function deriveBlockNote(facts: StageFacts, stages: StageMap, ctx: BlockContext): BlockNote | null {
  return (
    failedNote(facts, ctx) ??
    staleNote(facts, ctx) ??
    emptyIntakeNote(facts, ctx) ??
    activeNote(facts, ctx) ??
    (allStagesDone(stages) ? null : notShippedNote(facts, ctx))
  );
}

function failedNote(facts: StageFacts, ctx: BlockContext): BlockNote | null {
  if (facts.failed === null) return null;
  const stage = failedStage(facts.failed.type);
  const reason = facts.failed.error === '' ? '未知原因' : facts.failed.error;
  return {
    stage,
    tone: 'error',
    text: `卡在${STAGE_WORDS[stage]}：${reason}`,
    actionLabel: '去处理',
    route: stageRoute(ctx.dramaId, stage),
  };
}

function staleNote(facts: StageFacts, ctx: BlockContext): BlockNote | null {
  if (facts.staleHint !== true) return null;
  return {
    stage: 'planning',
    tone: 'warning',
    text: '剧集分析重跑过，方案比转写旧：出片前先重新规划',
    actionLabel: '重新规划',
    route: stageRoute(ctx.dramaId, 'planning'),
  };
}

function emptyIntakeNote(facts: StageFacts, ctx: BlockContext): BlockNote | null {
  if (facts.episodeCount !== 0) return null;
  return {
    stage: 'intake',
    tone: 'action',
    text: '建了库还没喂料：目录里没有识别到剧集文件',
    actionLabel: '去喂料',
    route: stageRoute(ctx.dramaId, 'intake'),
  };
}

function activeNote(facts: StageFacts, ctx: BlockContext): BlockNote | null {
  const stage = activeStageOf(facts.activeTypes);
  if (stage === null) return null;
  return {
    stage,
    tone: 'action',
    text: facts.activeLabel ?? `${STAGE_WORDS[stage]}进行中`,
    actionLabel: '去看',
    route: stageRoute(ctx.dramaId, stage),
  };
}

/** 没在跑也没失败、还没出片的剧：停滞催办 > 没开跑 > 跑过但账缺。有成品则无卡点。 */
function notShippedNote(facts: StageFacts, ctx: BlockContext): BlockNote | null {
  if (facts.workCount > 0) return null;
  const ageDays = (ctx.serverTimeMs - ctx.createdAtMs) / DAY_MS;
  if (ageDays >= STALLED_DAYS) {
    return {
      stage: 'export',
      tone: 'warning',
      text: `${String(facts.episodeCount)} 集已就位 ${String(Math.floor(ageDays))} 天，还没有成品`,
      actionLabel: '去出片',
      route: stageRoute(ctx.dramaId, 'export'),
    };
  }
  if (!facts.analysisEverCompleted) {
    return {
      stage: 'analysis',
      tone: 'action',
      text: '素材已就位，分析还没开跑',
      actionLabel: '去分析',
      route: stageRoute(ctx.dramaId, 'analysis'),
    };
  }
  return {
    stage: 'analysis',
    tone: 'action',
    text: '分析有过完成记录，方案还没见着',
    actionLabel: '去看',
    route: stageRoute(ctx.dramaId, 'analysis'),
  };
}

/** 「继续」按钮去哪：最深的活跃阶段说了算；全完成去成品库；否则回分析页。 */
export function continueRoute(dramaId: string, stages: StageMap): { readonly route: string; readonly label: string } {
  if (stages.planning === 'active' || stages.export === 'active') {
    return { route: `/projects/${dramaId}/produce`, label: '继续出片' };
  }
  if (allStagesDone(stages)) return { route: '/works', label: '看成品' };
  if (stages.planning === 'done' || stages.export === 'done') {
    return { route: `/projects/${dramaId}/produce`, label: '继续出片' };
  }
  return { route: `/projects/${dramaId}/analysis`, label: '继续分析' };
}

// ── 从 jobs.list 行提取剧维度事实（一次扫描，零额外 RPC）──────────────

/** ref_id=project_id 的任务类型；export→export_id、semantic→episode_id，挂不到剧。 */
const PROJECT_JOB_TYPES: ReadonlySet<string> = new Set(['analysis', 'prescreen', 'narration']);
const ANALYSIS_TYPES: ReadonlySet<string> = new Set(['analysis', 'prescreen']);

export type JobFacts = Pick<StageFacts, 'activeTypes' | 'activeLabel' | 'failed' | 'analysisEverCompleted'>;

/** jobs.list 按 updated_at 倒序（服务端默认排序），所以「第一条命中」即「最近一条」。 */
export function jobFactsFor(dramaId: string, jobs: readonly JobInfo[]): JobFacts {
  const activeTypes = new Set<string>();
  let activeLabel: string | null = null;
  let failed: JobFacts['failed'] = null;
  let analysisEverCompleted = false;
  for (const job of jobs) {
    if (job.ref_id !== dramaId || !PROJECT_JOB_TYPES.has(job.type)) continue;
    if (job.status === 'pending' || job.status === 'running') {
      activeTypes.add(job.type);
      activeLabel ??= job.label ?? null;
    } else if (job.status === 'failed' && failed === null) {
      failed = { type: job.type, error: job.error ?? '' };
    } else if (job.status === 'completed' && ANALYSIS_TYPES.has(job.type)) {
      analysisEverCompleted = true;
    }
  }
  return { activeTypes, activeLabel, failed, analysisEverCompleted };
}

/** 聚合 RPC 未落地期间的常量事实：三个可空字段全 null（宁灰勿假绿），账目字段来自 jobs 扫描。 */
export function degradedFacts(
  episodeCount: number,
  workCount: number,
  jobFacts: JobFacts,
): StageFacts {
  return {
    episodeCount,
    workCount,
    analyzedCount: null,
    planCount: null,
    staleHint: null,
    ...jobFacts,
  };
}
