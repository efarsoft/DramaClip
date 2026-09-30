/** 阶段②规划期视图：每条「模式×槽位」一行/一卡，三路服务端数据点亮状态——
 * 已落库方案（完成，升格方案卡）、jobs.error 增量（失败+原因原文）、当前 stage
 * （生成中）。行推导只依赖批次数据本身：离开页面再进来，队列原样还原。
 * 批次结束本组件让位给「挑方案」列表，那里决定出哪几条。 */
import { useState } from 'react';
import { Alert, Button, Tag } from 'antd';
import type { NarrationPlan } from '@dramaclip/protocol';
import { PageSection } from '../../components/layout/PageKit';
import { modeLabel } from '../../components/modeMeta';
import { tokens } from '../../styles/theme';
import type { PlanBatch } from './usePlanBatch';
import { LlmTraceModal } from './LlmTraceModal';

interface FailureLine {
  label: string;
  slot: string;
  reason: string;
}

/** jobs.error 的失败行解析：`模式·槽位: 原文`，分隔符「；」best-effort。 */
export function parseFailures(detail: string): FailureLine[] {
  const out: FailureLine[] = [];
  for (const line of detail.split('；')) {
    const mid = line.indexOf('·');
    const sep = line.indexOf(': ');
    if (mid <= 0 || sep < mid) continue;
    out.push({
      label: line.slice(0, mid),
      slot: line.slice(mid + 1, sep),
      reason: line.slice(sep + 2),
    });
  }
  return out;
}

export interface QueueSummary {
  /** 已完成的方案（按落库顺序）。 */
  done: NarrationPlan[];
  /** 失败行。 */
  failures: FailureLine[];
  /** 当前生成中的 stage 原文（空 = 恰在两条之间）。 */
  stageText: string;
  /** 仍在排队的条数（按进度百分比反推）。 */
  pendingCount: number;
}

export function buildQueueSummary(
  plans: NarrationPlan[],
  batchId: string | null,
  failDetail: string,
  stageText: string,
  percent: number,
): QueueSummary {
  const done = batchId === null ? [] : plans.filter((p) => p.batch_id === batchId);
  const failures = parseFailures(failDetail);
  const finished = done.length + failures.length;
  const total = percent > 0 && percent < 100 ? Math.ceil(finished / (percent / 100)) : finished;
  return {
    done,
    failures,
    stageText,
    pendingCount: Math.max(0, total - finished),
  };
}

const FAIL_COLOR = tokens.colorError;

export function PlanQueue({ batch }: { batch: PlanBatch }): React.ReactElement {
  const [tracesOpen, setTracesOpen] = useState(false);
  const summary = buildQueueSummary(
    batch.plans,
    batch.batchId,
    batch.failDetail,
    batch.stageText,
    batch.percent,
  );
  return (
    <PageSection title="② 规划队列" dense>
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
        {summary.done.map((plan) => (
          <DoneRow key={plan.id} plan={plan} />
        ))}
        {summary.failures.map((failure, index) => (
          <FailureRow key={`f${String(index)}`} failure={failure} onTrace={() => setTracesOpen(true)} />
        ))}
        {summary.stageText !== '' && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: tokens.spaceSm,
              padding: `${tokens.spaceXs} ${tokens.spaceSm}`,
              borderBottom: `1px solid ${tokens.borderSecondary}`,
            }}
          >
            <span
              style={{ width: 6, height: 6, borderRadius: tokens.radiusDot, background: tokens.colorInfo, flexShrink: 0 }}
            />
            <span style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, color: tokens.textPrimary }}>
              {summary.stageText}
            </span>
            <span style={{ marginLeft: 'auto', flexShrink: 0, fontSize: tokens.text.badge.size, color: tokens.colorInfo }}>
              生成中
            </span>
          </div>
        )}
        {summary.pendingCount > 0 && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: tokens.spaceSm,
              padding: `${tokens.spaceXs} ${tokens.spaceSm}`,
              borderBottom: `1px solid ${tokens.borderSecondary}`,
            }}
          >
            <span
              style={{ width: 6, height: 6, borderRadius: tokens.radiusDot, background: tokens.textTertiary, flexShrink: 0 }}
            />
            <span style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, color: tokens.textTertiary }}>
              其余 {String(summary.pendingCount)} 条排队中
            </span>
          </div>
        )}
      </div>
      {summary.done.length > 0 && (
        <Alert
          style={{ marginTop: tokens.spaceMd }}
          type="info"
          showIcon
          title={`已完成 ${String(summary.done.length)} 条——批次结束后进入「挑方案」勾选出片`}
        />
      )}
      <LlmTraceModal open={tracesOpen} onClose={() => setTracesOpen(false)} />
    </PageSection>
  );
}

function DoneRow({ plan }: { plan: NarrationPlan }): React.ReactElement {
  const label = modeLabel(plan.narration_mode);
  const hook = plan.plan_data.narration_texts[0]?.text ?? '';
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: tokens.spaceSm,
        padding: `${tokens.spaceSm} 0`,
        borderBottom: `1px solid ${tokens.borderSecondary}`,
      }}
    >
      <Tag color="gold" style={{ marginRight: 0, flexShrink: 0 }}>
        {plan.angle === null || plan.angle === undefined || plan.angle === '' ? label : plan.angle}
      </Tag>
      <strong style={{ color: tokens.textPrimary, fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, flexShrink: 0 }}>
        {label}
      </strong>
      <span
        style={{
          fontSize: tokens.text.meta.size,
          color: tokens.textTertiary,
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
        title={hook}
      >
        {hook}
      </span>
      <Tag color="success" style={{ marginLeft: 'auto', marginRight: 0, flexShrink: 0 }}>
        完成
      </Tag>
    </div>
  );
}

function FailureRow({ failure, onTrace }: { failure: FailureLine; onTrace: () => void }): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: tokens.spaceSm,
        padding: `${tokens.spaceXs} ${tokens.spaceSm}`,
        borderBottom: `1px solid ${tokens.borderSecondary}`,
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: tokens.radiusDot, background: FAIL_COLOR, flexShrink: 0 }} />
      <span style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, color: tokens.textPrimary, flexShrink: 0 }}>
        {failure.label} · {failure.slot}
      </span>
      <span
        style={{
          fontSize: tokens.text.badge.size,
          color: FAIL_COLOR,
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
        title={failure.reason}
      >
        {failure.reason}
      </span>
      <Button size="small" type="text" style={{ marginLeft: 'auto', flexShrink: 0 }} onClick={onTrace}>
        往返
      </Button>
      <span style={{ fontSize: tokens.text.badge.size, color: FAIL_COLOR, flexShrink: 0 }}>失败</span>
    </div>
  );
}
