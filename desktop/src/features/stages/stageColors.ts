/** 阶段灯色板：StageMicro（芯片排）与 StageBar（大阶段条）共用同一份映射。
 *
 * 词汇与颜色是跨屏语言（卷三意见 07）：同一个状态在工作台、剧库、剧壳三处
 * 必须同色同词。样式常量放这里而不是逻辑层（stageState.ts 保持零样式依赖）。
 */
import { tokens } from '../../styles/theme';
import type { BlockTone, StageState } from './stageState';

export const STATE_COLOR: Readonly<Record<StageState, string>> = {
  idle: tokens.textTertiary,
  active: tokens.colorInfo,
  done: tokens.colorSuccess,
  stale: tokens.colorWarning,
  unknown: tokens.textTertiary,
};

export const TONE_META: Readonly<Record<BlockTone, { color: string; soft: string; danger: boolean }>> = {
  error: { color: tokens.colorError, soft: tokens.errorSoft, danger: true },
  warning: { color: tokens.colorWarning, soft: tokens.warningSoft, danger: false },
  action: { color: tokens.colorInfo, soft: tokens.accentSoft, danger: false },
};
