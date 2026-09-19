/**
 * 开工就绪度卡：四环节（转写→文案→配音→渲染）逐格绿/红，加「待修资产」清单。
 * 格子的结论全部来自 workReadiness（设置值 + 体检 + 真实渲染版本），缺哪一件这里就点得进去。
 */
import { Button } from 'antd';
import type { ReactElement } from 'react';
import type { ModelInfo } from '@dramaclip/protocol';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';
import type { EngineTab, Reports } from './assetState';
import { incompleteAssets } from './assetState';
import type { ReadinessStep } from './workReadiness';

type GoTab = (tab: EngineTab) => void;

export function ReadinessCard({
  steps,
  models,
  reports,
  onGo,
}: {
  steps: readonly ReadinessStep[];
  models: readonly ModelInfo[];
  reports: Reports;
  onGo: GoTab;
}): ReactElement {
  const pending = steps.filter((step) => !step.ok);
  return (
    <div
      style={{
        padding: `${tokens.spaceMd} ${tokens.spaceLg}`,
        borderRadius: tokens.radiusCard,
        border: `1px solid ${pending.length === 0 ? tokens.borderSecondary : tokens.colorWarning}`,
        background: tokens.bgContainer,
      }}
    >
      <Headline pending={pending.length} />
      <div style={{ display: 'flex', alignItems: 'stretch', gap: tokens.spaceSm }}>
        {steps.map((step, index) => (
          <StepNode key={step.key} step={step} first={index === 0} onGo={onGo} />
        ))}
      </div>
      {incompleteAssets(models, reports).map((item) => (
        <BrokenRow key={item.model.model_id} item={item} onGo={onGo} />
      ))}
    </div>
  );
}

function Headline({ pending }: { pending: number }): ReactElement {
  return (
    <div style={{ ...mixins.sectionTitleRow(), marginBottom: tokens.spaceMd }}>
      <span style={{ ...mixins.sectionBar(), marginRight: tokens.spaceSm }} />
      <span style={{ fontSize: tokens.fontBody, fontWeight: 600, color: tokens.textPrimary }}>
        开工就绪度
      </span>
      <span
        style={{
          marginLeft: tokens.spaceMd,
          fontSize: tokens.fontMicro,
          color: pending === 0 ? tokens.colorSuccess : tokens.colorWarning,
        }}
      >
        {pending === 0 ? '全绿 · 可提交任务' : `${String(pending)} 项待办`}
      </span>
    </div>
  );
}

/** 待修资产：没在用它所以不影响本次开工，但切过去会直接失败。 */
function BrokenRow({
  item,
  onGo,
}: {
  item: { model: ModelInfo; note: string; tab: EngineTab };
  onGo: GoTab;
}): ReactElement {
  return (
    <div
      style={{
        marginTop: tokens.spaceMd,
        display: 'flex',
        alignItems: 'center',
        gap: tokens.spaceSm,
        minWidth: 0,
      }}
    >
      <span style={mixins.statusDot(tokens.colorError)} />
      <span
        style={{
          fontSize: tokens.fontCaption,
          color: tokens.textSecondary,
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
        title={item.note}
      >
        资产完整性：{item.model.name} {item.note} —— 现在没在用它，切过去会直接失败
      </span>
      <Button
        size="small"
        style={{ marginLeft: 'auto', flexShrink: 0 }}
        onClick={() => {
          onGo(item.tab);
        }}
      >
        去修复
      </Button>
    </div>
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
        <span style={{ alignSelf: 'center', color: tokens.textTertiary, fontSize: tokens.fontBody }}>›</span>
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
          <span style={{ fontSize: tokens.fontCaption, fontWeight: 600, color: tokens.textPrimary }}>
            {step.index} {step.label}
          </span>
        </div>
        <div
          style={{
            marginTop: 2,
            fontSize: tokens.fontMicro,
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
