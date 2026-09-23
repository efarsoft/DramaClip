/** 项目壳大阶段条（卷三图 3 / 意见 06）：位置指示 + 状态灯 + 在跑进度。
 *
 * 四段横向排开，当前路由所在段高亮；段可点击——analysis/produce 都是真实路由，
 * ①② 归分析页、③④ 归出片页（带 ?focus= 滚到对应卡片区），点了真跳不是装饰。
 * 在跑段显示服务端进度百分比（在跑封顶 99，不本地推算）。灯色与卡点句和矩阵/
 * 剧卡共用 stageState 词汇（意见 07）；账本缺席时 stages 传 null，全灰不装绿。
 */
import { Link, useNavigate } from 'react-router-dom';
import type { CSSProperties, ReactElement } from 'react';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';
import {
  STAGE_ORDER,
  stageLabel,
  stageRoute,
  type BlockNote,
  type StageKey,
  type StageMap,
  type StageState,
} from './stageState';
import { STATE_COLOR, TONE_META } from './stageColors';
import { BlockNoteLine } from './StageMicro';

export interface StageBarProps {
  readonly projectId: string;
  /** null = 账本还在取或取不到：全灰灯。 */
  readonly stages: StageMap | null;
  readonly note: BlockNote | null;
  /** 账本缺席原因原文；null = 账全在。 */
  readonly factsError: string | null;
  /** 当前路由落在哪一段（analysis 路由 → ②，produce 路由 → ③）。 */
  readonly current: StageKey;
  /** 最近在跑任务落在哪一段 + 进度（0-100，服务端在跑封顶 99）；没有则 null，不显示假数字。 */
  readonly activeStage: StageKey | null;
  readonly activeProgress: number | null;
}

/** 段目标带 focus 参数：出片页内 ③④ 各有实体卡片区，滚过去而不是只到页顶。 */
function segmentTarget(projectId: string, key: StageKey): string {
  const base = stageRoute(projectId, key);
  if (key === 'planning' || key === 'export') return `${base}?focus=${key}`;
  return base;
}

export function StageBar({ projectId, stages, note, factsError, current, activeStage, activeProgress }: StageBarProps): ReactElement {
  const navigate = useNavigate();
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
      <nav aria-label="生产线阶段" style={{ display: 'flex', gap: tokens.spaceXs }}>
        {STAGE_ORDER.map((key) => (
          <StageSegment
            key={key}
            stageKey={key}
            state={stages === null ? 'unknown' : stages[key]}
            tone={note !== null && note.stage === key ? note.tone : null}
            current={key === current}
            progress={key === activeStage ? activeProgress : null}
            to={segmentTarget(projectId, key)}
          />
        ))}
      </nav>
      {note !== null ? (
        <BlockNoteLine
          note={note}
          onAction={(route) => {
            void navigate(route);
          }}
        />
      ) : null}
      {note === null && factsError !== null && (
        <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>
          {`阶段账不可用：${factsError}。灯点灰是「取不到」，不是「没进行」。`}
        </span>
      )}
    </div>
  );
}

function StageSegment({
  stageKey,
  state,
  tone,
  current,
  progress,
  to,
}: {
  stageKey: StageKey;
  state: StageState;
  tone: BlockNote['tone'] | null;
  current: boolean;
  progress: number | null;
  to: string;
}): ReactElement {
  const dotColor = tone !== null ? TONE_META[tone].color : STATE_COLOR[state];
  const style: CSSProperties = {
    flex: 1,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: tokens.spaceXs,
    padding: `${tokens.spaceSm} ${tokens.spaceMd}`,
    borderRadius: tokens.radiusControl,
    border: `1px solid ${current ? tokens.colorPrimary : tokens.borderSecondary}`,
    background: current ? tokens.accentSoft : tokens.bgContainer,
    color: current ? tokens.colorPrimary : tokens.textSecondary,
    fontSize: tokens.text.meta.size,
    lineHeight: tokens.text.meta.leading,
    textDecoration: 'none',
    whiteSpace: 'nowrap',
  };
  return (
    <Link to={to} style={style} aria-current={current ? 'step' : undefined}>
      {state === 'idle' ? (
        <span
          style={{ ...mixins.statusDot(dotColor), background: 'transparent', border: `1px solid ${dotColor}`, boxShadow: 'none' }}
        />
      ) : (
        <span style={mixins.statusDot(dotColor)} />
      )}
      {stageLabel(stageKey)}
      {state === 'active' && progress !== null ? ` · ${String(progress)}%` : ''}
      {state === 'unknown' ? ' —' : ''}
    </Link>
  );
}
