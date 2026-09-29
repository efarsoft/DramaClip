/** 阶段②规划期视图：每条「模式×槽位」一行，三路数据点亮状态——
 * 已落库方案（完成）、jobs.error 增量（失败+原因原文）、当前 stage（生成中）。
 * 执行是全局串行的（模式按序、槽位按序），第一个待定行即当前行。
 * 批次结束本组件让位给「挑方案」列表，那里决定出哪几条。 */
import { useState } from 'react';
import { Alert, Button, Tag } from 'antd';
import type { NarrationMode, NarrationPlan } from '@dramaclip/protocol';
import { PageSection } from '../../components/layout/PageKit';
import { modeLabel } from '../../components/modeMeta';
import { tokens } from '../../styles/theme';
import type { PlanBatch } from './usePlanBatch';
import { LlmTraceModal } from './LlmTraceModal';

export interface QueueRow {
  mode: NarrationMode;
  label: string;
  index: number;
  status: 'pending' | 'running' | 'done' | 'failed';
  /** 完成行带方案角度名；失败行带原因原文。 */
  angle?: string;
  reason?: string;
}

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

export function buildQueueRows(
  modes: NarrationMode[],
  k: number,
  plans: NarrationPlan[],
  batchId: string | null,
  failDetail: string,
  stageText: string,
): QueueRow[] {
  const byKey = new Map<string, NarrationPlan>();
  for (const plan of plans) {
    if (batchId !== null && plan.batch_id !== null && plan.batch_id !== undefined && plan.batch_id !== batchId) {
      continue;
    }
    byKey.set(`${plan.narration_mode}#${plan.variant_index ?? 1}`, plan);
  }
  const failures = parseFailures(failDetail);
  const rows: QueueRow[] = [];
  for (const mode of modes) {
    const label = modeLabel(mode);
    for (let index = 1; index <= k; index += 1) {
      const plan = byKey.get(`${mode}#${index}`);
      rows.push(
        plan !== undefined
          ? { mode, label, index, status: 'done', angle: plan.angle || `第${String(index)}条` }
          : { mode, label, index, status: 'pending' },
      );
    }
  }
  for (const failure of failures) {
    const numbered = /^第(\d+)条$/.exec(failure.slot);
    const target =
      numbered !== null
        ? rows.find(
            (row) => row.label === failure.label && row.index === Number(numbered[1]) && row.status === 'pending',
          )
        : rows.find((row) => row.label === failure.label && row.status === 'pending');
    if (target !== undefined) {
      target.status = 'failed';
      target.reason = failure.reason;
    }
  }
  const running = rows.find((row) => row.status === 'pending');
  if (running !== undefined && stageText !== '' && stageText.startsWith(`${running.label}·`)) {
    running.status = 'running';
  }
  return rows;
}

const STATUS_META: Record<QueueRow['status'], { text: string; color: string }> = {
  done: { text: '完成', color: tokens.colorSuccess },
  running: { text: '生成中', color: tokens.colorInfo },
  failed: { text: '失败', color: tokens.colorError },
  pending: { text: '排队', color: tokens.textTertiary },
};

export function PlanQueue({
  batch,
  modes,
  k,
}: {
  batch: PlanBatch;
  modes: NarrationMode[];
  k: number;
}): React.ReactElement {
  const [tracesOpen, setTracesOpen] = useState(false);
  const rows = buildQueueRows(modes, k, batch.plans, batch.batchId, batch.failDetail, batch.stageText);
  const doneCount = rows.filter((row) => row.status === 'done').length;
  return (
    <PageSection
      title="② 规划队列"
      dense
      extra={
        <Button size="small" type="text" onClick={() => setTracesOpen(true)}>
          LLM 往返记录
        </Button>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs }}>
        {rows.map((row) => {
          const meta = STATUS_META[row.status];
          return (
            <div
              key={`${row.mode}#${String(row.index)}`}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: tokens.spaceSm,
                padding: `${tokens.spaceXs} ${tokens.spaceSm}`,
                borderBottom: `1px solid ${tokens.borderSecondary}`,
              }}
            >
              <span
                style={{ width: 6, height: 6, borderRadius: tokens.radiusDot, background: meta.color, flexShrink: 0 }}
              />
              <span
                style={{
                  fontSize: tokens.text.body.size,
                  lineHeight: tokens.text.body.leading,
                  color: tokens.textPrimary,
                  minWidth: 0,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
                title={row.reason ?? row.angle}
              >
                {row.label} · {row.angle ?? `第${String(row.index)}条`}
              </span>
              {row.status === 'failed' && (
                <span
                  style={{
                    fontSize: tokens.text.badge.size,
                    color: tokens.colorError,
                    minWidth: 0,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {row.reason}
                </span>
              )}
              <span style={{ marginLeft: 'auto', flexShrink: 0 }}>
                {row.status === 'done' ? (
                  <Tag color="success" style={{ marginRight: 0 }}>
                    完成
                  </Tag>
                ) : (
                  <span style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: meta.color }}>
                    {meta.text}
                  </span>
                )}
              </span>
            </div>
          );
        })}
      </div>
      {doneCount > 0 && (
        <Alert
          style={{ marginTop: tokens.spaceMd }}
          type="info"
          showIcon
          title={`已完成 ${String(doneCount)} 条——批次结束后进入「挑方案」勾选出片`}
        />
      )}
      <LlmTraceModal open={tracesOpen} onClose={() => setTracesOpen(false)} />
    </PageSection>
  );
}
