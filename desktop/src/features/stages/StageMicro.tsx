/** 阶段灯与卡点行的共享 UI 词汇（卷三意见 07：共词汇不共组件）。
 *
 * 工作台矩阵与剧库五要素卡都渲染同一份 stageState 词汇表：灯色、阶段词、
 * 卡点句式跨屏一致；布局各排各的。度量全走 tokens/mixins，零手抄数字。
 */
import { Button } from 'antd';
import type { CSSProperties, ReactElement } from 'react';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';
import {
  STAGE_ORDER,
  stageLabel,
  type BlockNote,
  type BlockTone,
  type StageKey,
  type StageMap,
  type StageState,
} from './stageState';
import { STATE_COLOR, TONE_META } from './stageColors';

/** 四阶段灯排。卡点所在阶段用 note.tone 改色，其余灯照常——一眼看出卡在哪。 */
export function StageMicro({ stages, note }: { stages: StageMap; note?: BlockNote | null }): ReactElement {
  const blocked = note ?? null;
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: tokens.spaceXs, flexWrap: 'wrap' }}>
      {STAGE_ORDER.map((key) => (
        <StageChip
          key={key}
          stageKey={key}
          state={stages[key]}
          tone={blocked !== null && blocked.stage === key ? blocked.tone : null}
        />
      ))}
    </span>
  );
}

function StageChip({
  stageKey,
  state,
  tone,
}: {
  stageKey: StageKey;
  state: StageState;
  tone: BlockTone | null;
}): ReactElement {
  const color = tone !== null ? TONE_META[tone].color : STATE_COLOR[state];
  const chipStyle: CSSProperties = {
    ...mixins.chip(),
    display: 'inline-flex',
    alignItems: 'center',
    gap: tokens.spaceXs,
  };
  if (tone !== null) chipStyle.background = TONE_META[tone].soft;
  return (
    <span style={chipStyle}>
      {state === 'idle' ? (
        // 未开始 = 空心点；unknown = 灰实心点 + 「—」：灰要看得见是「不知道」，不是「没有」
        <span
          style={{ ...mixins.statusDot(color), background: 'transparent', border: `1px solid ${color}`, boxShadow: 'none' }}
        />
      ) : (
        <span style={mixins.statusDot(color)} />
      )}
      {stageLabel(stageKey)}
      {state === 'unknown' ? ' —' : ''}
    </span>
  );
}

/** 卡点行：灯色随 tone，文案可见区两行截断但 title 给全文——原文另在任务中心全量可查。 */
export function BlockNoteLine({ note, onAction }: { note: BlockNote; onAction: (route: string) => void }): ReactElement {
  const tone = TONE_META[note.tone];
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm, minWidth: 0 }}>
      <span style={mixins.statusDot(tone.color)} />
      <span
        title={note.text}
        style={{
          fontSize: tokens.text.meta.size,
          lineHeight: tokens.text.meta.leading,
          color: tone.color,
          overflow: 'hidden',
          display: '-webkit-box',
          WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical',
          wordBreak: 'break-all',
        }}
      >
        {note.text}
      </span>
      <Button
        size="small"
        danger={tone.danger}
        style={{ marginLeft: 'auto', flexShrink: 0 }}
        onClick={() => {
          onAction(note.route);
        }}
      >
        {note.actionLabel}
      </Button>
    </span>
  );
}
