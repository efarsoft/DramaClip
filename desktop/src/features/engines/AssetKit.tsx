/** 引擎中心共用小件：状态点/徽标、评级点、总览卡壳——生效卡与资产库共用，保证三域同构。 */
import type { ReactNode } from 'react';
import { Card } from 'antd';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';
import { type AssetState, stateLabel } from './assetState';

/** 五态配色：绿只在「体检通过的已装已接入」上出现，其余一律不假装。 */
const STATE_TONE: Record<AssetState, string> = {
  ready: tokens.colorSuccess,
  unverified: tokens.colorInfo,
  incomplete: tokens.colorError,
  missing: tokens.colorWarning,
  reserve: tokens.textTertiary,
};

export function StateDot({ state }: { state: AssetState }): ReactNode {
  return <span style={mixins.statusDot(STATE_TONE[state])} />;
}

export function StateBadge({
  state,
  note,
  progress,
}: {
  state: AssetState;
  note?: string;
  progress?: number;
}): ReactNode {
  const tone = STATE_TONE[state];
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: tokens.spaceXs, minWidth: 0 }}>
      <StateDot state={state} />
      <span style={{ fontSize: tokens.fontCaption, color: tone, flexShrink: 0 }}>
        {progress !== undefined ? `下载中 ${String(Math.floor(progress))}%` : stateLabel(state)}
      </span>
      {note !== undefined && (
        <span
          title={note}
          style={{
            fontSize: tokens.fontMicro,
            color: tokens.textTertiary,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {note}
        </span>
      )}
    </span>
  );
}

export function RatingDots({ label, level }: { label: string; level: number }): ReactNode {
  return (
    <span
      style={{ display: 'inline-flex', alignItems: 'center', gap: tokens.spaceXs }}
      title={`${label} ${String(level)}/5`}
    >
      <span style={{ fontSize: tokens.fontMicro, color: tokens.textTertiary }}>{label}</span>
      {[1, 2, 3, 4, 5].map((i) => (
        <span
          key={i}
          style={{
            width: 5,
            height: 5,
            borderRadius: tokens.radiusDot,
            background: i <= level ? tokens.colorPrimary : tokens.border,
          }}
        />
      ))}
    </span>
  );
}

/** 总览用的浅色卡壳：可选整卡点击（点对卡即跳对应域）。 */
export function SectionCard({
  onClick,
  children,
}: {
  onClick?: () => void;
  children: ReactNode;
}): React.ReactElement {
  return (
    <Card
      size="small"
      hoverable={onClick !== undefined}
      onClick={onClick}
      styles={{ body: { padding: `${tokens.spaceMd} ${tokens.spaceLg}`, height: '100%' } }}
    >
      {children}
    </Card>
  );
}
