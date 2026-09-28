/**
 * 方案卡只读判据（规格 §4.3）。
 *
 * K 条方案卡是用户判断「K 条是不是 K 个不同卖点」的唯一依据，
 * 所以这里宁可把空值、零值、缺失字段各写清楚一次，
 * 也不要让界面把「重叠 0%」显示成空白、把缺失角度名显示成 undefined。
 */
import type { NarrationPlan } from '@dramaclip/protocol';

/** 钩子首句在卡片里最多占这么多字——卡片一行放不下一整段独白。 */
export const HOOK_MAX = 40;
const SENTENCE_ENDS = /[。！？!?…]/;

export interface PlanCardView {
  readonly planId: string;
  readonly mode: string;
  /** 角度名；无解说的模式为空串。 */
  readonly angle: string;
  /** 模型自选这条角度的理由。 */
  readonly reason: string;
  /** 「取材 N 集」。 */
  readonly episodes: string;
  /** 钩子首句；原声模式为空串，界面据此不渲染这一行。 */
  readonly hook: string;
  /** 「取材重叠 NN%」；组内首条为「组内首条」。 */
  readonly overlap: string;
  /** 「剧本丢弃 N 段」；0 段或非编剧链为空串，界面不占行。 */
  readonly dropped: string;
  /** 过了转化门禁才能勾选出片。 */
  readonly pickable: boolean;
  /** 不能出片时的原因；可出片为空串。 */
  readonly gate: string;
}

export function planCardView(plan: NarrationPlan): PlanCardView {
  return {
    planId: plan.id,
    mode: plan.narration_mode,
    angle: plan.angle ?? '',
    reason: plan.angle_reason ?? '',
    episodes: `取材 ${String(plan.episode_ids.length)} 集`,
    hook: hookLine(plan),
    overlap: overlapText(plan.overlap_max),
    dropped: droppedText(plan.plan_data.dropped_segments),
    pickable: plan.status === 'ready',
    gate: plan.status === 'ready' ? '' : (plan.block_reason ?? '过不了转化门禁，不能出片'),
  };
}

function hookLine(plan: NarrationPlan): string {
  const first = plan.plan_data.narration_texts[0]?.text.trim() ?? '';
  if (first === '') return '';
  const end = first.search(SENTENCE_ENDS);
  if (end >= 0 && end < HOOK_MAX) return first.slice(0, end + 1);
  return `${first.slice(0, HOOK_MAX)}…`;
}

/** `null`/`undefined` = 没有兄弟可比；`0` = 一点没重——两者是两句话，不能合并。 */
function overlapText(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined) return '组内首条';
  return `取材重叠 ${String(Math.round(ratio * 100))}%`;
}

/** 清洗层丢了几段必须说出口：不说，方案看起来就像天生只有这么长。 */
function droppedText(count: number | undefined): string {
  if (!count || count <= 0) return '';
  return `剧本丢弃 ${String(count)} 段`;
}

/** 每模式默认推荐：首个可出片方案（列表已按评分降序——有分即最高分）。
 *  同模式全不可出片则该模式不推荐，不硬点。 */
export function recommendedIds(plans: NarrationPlan[]): string[] {
  const best = new Map<string, NarrationPlan[]>();
  for (const plan of plans) {
    if (!planCardView(plan).pickable) continue;
    const list = best.get(plan.narration_mode) ?? [];
    if (list.length < 2) best.set(plan.narration_mode, [...list, plan]);
  }
  return [...best.values()].flatMap((list) => list.map((plan) => plan.id));
}
