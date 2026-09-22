/**
 * 生效卡：ASR / TTS 两个域共用同一块位、同一卡型（对应重规划 P3）。
 * 卡上只出现两类事实——设置里的当前选择，和资产库对那个选择体检出的结论。
 */
import type { ReactNode } from 'react';
import { tokens } from '../../styles/theme';
import type { AssetState } from './assetState';
import { StateBadge } from './AssetKit';

export interface ActiveProp {
  readonly label: string;
  readonly value: ReactNode;
}

export interface ActiveCardProps {
  domain: string;
  title: string;
  /** 无模型引擎（云端）时的说明，如「无需模型，需联网」。 */
  hint?: string;
  state: AssetState | null;
  stateNote?: string;
  progress?: number;
  picker?: ReactNode;
  actions?: ReactNode;
  props: readonly ActiveProp[];
  /** 卡尾补语：只放该引擎的使用说明，不放结论性状态（状态归 StateBadge）。 */
  footnote?: ReactNode;
}

export function ActiveEngineCard({
  domain,
  title,
  hint,
  state,
  stateNote,
  progress,
  picker,
  actions,
  props,
  footnote,
}: ActiveCardProps): React.ReactElement {
  return (
    <section
      style={{
        background: tokens.bgContainer,
        border: `1px solid ${tokens.borderSecondary}`,
        borderRadius: tokens.radiusCard,
        boxShadow: tokens.shadowCard,
        padding: `${tokens.spaceLg} ${tokens.spaceLg} ${tokens.spaceMd}`,
      }}
    >
      <CardHead domain={domain} picker={picker} actions={actions} />
      <TitleLine title={title} hint={hint} state={state} stateNote={stateNote} progress={progress} />
      <PropGrid props={props} />
      {footnote !== undefined && (
        <div style={{ marginTop: tokens.spaceSm, fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
          {footnote}
        </div>
      )}
    </section>
  );
}

function CardHead({
  domain,
  picker,
  actions,
}: {
  domain: string;
  picker?: ReactNode;
  actions?: ReactNode;
}): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: tokens.spaceMd,
        paddingBottom: tokens.spaceMd,
        borderBottom: `1px solid ${tokens.borderSecondary}`,
      }}
    >
      <span style={{ width: 3, height: 13, borderRadius: tokens.radiusDot, background: tokens.gradientAccent }} />
      <span style={{ fontSize: tokens.text.cardTitle.size, lineHeight: tokens.text.cardTitle.leading, fontWeight: 600, color: tokens.textPrimary }}>当前生效</span>
      <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>{domain}</span>
      <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: tokens.spaceSm }}>
        {picker}
        {actions}
      </span>
    </div>
  );
}

function TitleLine({
  title,
  hint,
  state,
  stateNote,
  progress,
}: {
  title: string;
  hint?: string;
  state: AssetState | null;
  stateNote?: string;
  progress?: number;
}): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: tokens.spaceMd,
        padding: `${tokens.spaceMd} 0`,
        flexWrap: 'wrap',
      }}
    >
      <span style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, fontWeight: 600, color: tokens.textPrimary }}>{title}</span>
      {state === null ? (
        <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>{hint ?? '无需本地模型'}</span>
      ) : (
        <StateBadge state={state} note={stateNote} progress={progress} />
      )}
    </div>
  );
}

function PropGrid({ props }: { props: readonly ActiveProp[] }): React.ReactElement {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
        gap: tokens.spaceLg,
        paddingTop: tokens.spaceMd,
        borderTop: `1px solid ${tokens.borderSecondary}`,
      }}
    >
      {props.map((prop) => (
        <div key={prop.label} style={{ minWidth: 0 }}>
          <span style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>{prop.label}</span>
          <div
            style={{
              fontSize: tokens.text.meta.size,
              lineHeight: tokens.text.meta.leading,
              color: tokens.textSecondary,
              marginTop: 2,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {prop.value}
          </div>
        </div>
      ))}
    </div>
  );
}
