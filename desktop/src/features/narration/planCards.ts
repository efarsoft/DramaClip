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
