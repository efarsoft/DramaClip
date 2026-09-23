/**
 * 就绪与修复（§10.4 第 1 段）：四环节（转写→文案→配音→渲染）逐格绿/红 + 待办清单。
 * 格子结论全部来自 workReadiness（设置值 + 校验 + 自检 + 真实渲染版本）；
 * 清单每行按 §10.5 三要素写「现象 + 后果 + 动作」——动作是真按钮（清理残留/迁移/
 * 删副本/自检/校验/重下，由判据召唤，见 RepairActions），按钮名与动作同权重，不做跳转按钮；
 * 「定位」只是真动作之外的补充（同页锚点，跳段不跳屏）。
 */
import { Button } from 'antd';
import type { ReactElement } from 'react';
import type { ModelInfo, SelftestResults } from '@dramaclip/protocol';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';
import type { AttentionAsset, EngineTab, Reports } from './assetState';
import { activeAsset, assetState, attentionAssets, reportFor } from './assetState';
import { RepairActions } from './RepairActions';
import type { ReadinessStep } from './workReadiness';

type GoTab = (tab: EngineTab) => void;

const noop = (): void => undefined;
const noopVerify = (): void => undefined;

const SEVERITY_COLOR = {
  fail: tokens.colorError,
  unconfirmed: tokens.colorWarning,
  warn: tokens.colorWarning,
} as const;

export function ReadinessCard({
  steps,
  models,
  reports,
  selftests,
  settings,
  onGo,
  onChanged,
  onVerify,
}: {
  steps: readonly ReadinessStep[];
  models: readonly ModelInfo[];
  reports: Reports;
  selftests?: SelftestResults;
  settings?: Readonly<Record<string, string>>;
  onGo: GoTab;
  onChanged?: () => void;
  onVerify?: (modelId: string) => void;
}): ReactElement {
  const pending = steps.filter((step) => !step.ok);
  const unconfirmed = countUnconfirmed(models, reports, selftests, settings ?? {});
  return (
    <div
      style={{
        padding: `${tokens.spaceMd} ${tokens.spaceLg}`,
        borderRadius: tokens.radiusCard,
        border: `1px solid ${pending.length === 0 ? tokens.borderSecondary : tokens.colorWarning}`,
        background: tokens.bgContainer,
      }}
    >
      <Headline pending={pending.length} unconfirmed={unconfirmed} />
      <div style={{ display: 'flex', alignItems: 'stretch', gap: tokens.spaceSm }}>
        {steps.map((step, index) => (
          <StepNode key={step.key} step={step} first={index === 0} onGo={onGo} />
        ))}
      </div>
      {attentionAssets(models, reports, selftests).map((item) => (
        <AttentionRow
          key={item.model.model_id}
          item={item}
          onGo={onGo}
          onChanged={onChanged ?? noop}
          onVerify={onVerify ?? noopVerify}
        />
      ))}
    </div>
  );
}

/** 标题句（§10.5）：全绿只在参与就绪判定的资产全部 ready 时出现；有未证实能用的就直说。 */
function Headline({ pending, unconfirmed }: { pending: number; unconfirmed: number }): ReactElement {
  const text =
    pending === 0
      ? '全绿 · 可提交任务'
      : unconfirmed > 0
        ? `${String(unconfirmed)} 项未校验——未确认能用`
        : `${String(pending)} 项待办`;
  return (
    <div style={{ ...mixins.sectionTitleRow(), marginBottom: tokens.spaceMd }}>
      <span style={{ ...mixins.sectionBar(), marginRight: tokens.spaceSm }} />
      <span style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, fontWeight: 600, color: tokens.textPrimary }}>
        开工就绪度
      </span>
      <span
        style={{
          marginLeft: tokens.spaceMd,
          fontSize: tokens.text.badge.size,
          lineHeight: tokens.text.badge.leading,
          color: pending === 0 ? tokens.colorSuccess : tokens.colorWarning,
        }}
      >
        {text}
      </span>
    </div>
  );
}

/** 「N 项未校验」的 N：只数参与就绪判定的那两件（当前生效资产）。 */
function countUnconfirmed(
  models: readonly ModelInfo[],
  reports: Reports,
  selftests: SelftestResults | undefined,
  settings: Readonly<Record<string, string>>,
): number {
  let count = 0;
  for (const kind of ['asr', 'tts'] as const) {
    const active = activeAsset(models, kind, settings);
    if (active === undefined) continue;
    const state = assetState(active, reportFor(reports, active.model_id), selftests?.[active.model_id]);
    if (state === 'unverified' || state === 'untested') count += 1;
  }
  return count;
}

/** 待办行：现象 + 后果写在文案里，修法是真按钮（RepairActions 按判据召唤）+ 校验 + 定位。 */
function AttentionRow({
  item,
  onGo,
  onChanged,
  onVerify,
}: {
  item: AttentionAsset;
  onGo: GoTab;
  onChanged: () => void;
  onVerify: (modelId: string) => void;
}): ReactElement {
  return (
    <div
      style={{
        marginTop: tokens.spaceMd,
        display: 'flex',
        alignItems: 'center',
        gap: tokens.spaceSm,
        minWidth: 0,
        flexWrap: 'wrap',
      }}
    >
      <span style={mixins.statusDot(SEVERITY_COLOR[item.severity])} />
      <span
        style={{
          fontSize: tokens.text.meta.size,
          lineHeight: tokens.text.meta.leading,
          color: tokens.textSecondary,
          minWidth: 0,
        }}
        title={`${item.note} —— ${item.consequence}`}
      >
        {item.model.name}：{item.note} —— {item.consequence}
      </span>
      <AttentionActions item={item} onGo={onGo} onChanged={onChanged} onVerify={onVerify} />
    </div>
  );
}

/** 行内动作区：校验（能自动档）+ 判据召唤的修复 + 定位（同页锚点，补充不是替代）。 */
function AttentionActions({
  item,
  onGo,
  onChanged,
  onVerify,
}: {
  item: AttentionAsset;
  onGo: GoTab;
  onChanged: () => void;
  onVerify: (modelId: string) => void;
}): ReactElement {
  return (
    <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: tokens.spaceSm, flexShrink: 0 }}>
      {item.report === undefined && (
        <Button
          size="small"
          onClick={() => {
            onVerify(item.model.model_id);
          }}
        >
          校验
        </Button>
      )}
      <RepairActions
        model={item.model}
        report={item.report}
        selftest={item.selftest}
        onChanged={onChanged}
        onVerify={onVerify}
      />
      <Button
        size="small"
        type="text"
        onClick={() => {
          onGo(item.tab);
        }}
      >
        定位
      </Button>
    </span>
  );
}

function StepNode({
  step,
  first,
  onGo,
}: {
  step: ReadinessStep;
  first: boolean;
  onGo: GoTab;
}): ReactElement {
  const tone = step.ok ? tokens.colorSuccess : tokens.colorError;
  return (
    <>
      {!first && (
        <span style={{ alignSelf: 'center', color: tokens.textTertiary, fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading }}>›</span>
      )}
      <div
        onClick={() => {
          if (step.tab !== null) onGo(step.tab);
        }}
        style={{
          flex: 1,
          minWidth: 0,
          padding: `${tokens.spaceSm} ${tokens.spaceMd}`,
          borderRadius: tokens.radiusControl,
          border: `1px solid ${step.ok ? tokens.borderSecondary : tone}`,
          background: step.ok ? tokens.bgElevated : tokens.bgContainer,
          cursor: step.tab === null ? 'default' : 'pointer',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceXs }}>
          <span style={mixins.statusDot(tone)} />
          <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, fontWeight: 600, color: tokens.textPrimary }}>
            {step.index} {step.label}
          </span>
        </div>
        <div
          style={{
            marginTop: 2,
            fontSize: tokens.text.badge.size,
            lineHeight: tokens.text.badge.leading,
            color: step.ok ? tokens.textSecondary : tone,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {step.detail}
        </div>
      </div>
    </>
  );
}
