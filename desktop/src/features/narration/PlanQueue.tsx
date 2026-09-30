/** 阶段②规划期视图：每条「模式×槽位」一行/一卡，状态来自三路服务端数据——
 * 已落库方案（完成，含 hook 预览）、jobs.error 增量（失败+原因原文，可查往返）、
 * 当前 stage（生成中）。提交规格（模式×条数）持久化在 localStorage：0% 时就能画出
 * 完整骨架，页面重进/重启后照样还原。批次结束本组件让位给「挑方案」列表。 */
import { useState } from 'react';
import { Alert, Button, Tag } from 'antd';
import type { NarrationMode, NarrationPlan } from '@dramaclip/protocol';
import { PageSection } from '../../components/layout/PageKit';
import { MODE_INFO, modeLabel } from '../../components/modeMeta';
import { tokens } from '../../styles/theme';
import type { PlanBatch } from './usePlanBatch';
import { LlmTraceModal } from './LlmTraceModal';

export interface BatchSpec {
  modes: NarrationMode[];
  k: number;
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

type RowStatus = 'pending' | 'running' | 'done' | 'failed';

interface QueueRow {
  mode: NarrationMode;
  label: string;
  index: number;
  status: RowStatus;
  plan?: NarrationPlan;
  reason?: string;
}

/** 队列骨架合成：规格（模式×条数）定行集，三路数据逐行盖章。
 *  spec 缺失（如换了浏览器重进）退化为汇总形态：完成卡 + 失败行 + 当前 stage。 */
export function buildQueueRows(
  spec: BatchSpec,
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
  for (const mode of spec.modes) {
    const label = modeLabel(mode);
    for (let index = 1; index <= spec.k; index += 1) {
      const plan = byKey.get(`${mode}#${index}`);
      rows.push(
        plan !== undefined
          ? { mode, label, index, status: 'done', plan }
          : { mode, label, index, status: 'pending' },
      );
    }
  }
  for (const failure of failures) {
    const numbered = /^第(\d+)条$/.exec(failure.slot);
    const modeByLabel = MODE_INFO.find((item) => modeLabel(item.mode as NarrationMode) === failure.label);
    const target =
      numbered !== null && modeByLabel !== undefined
        ? rows.find(
            (row) =>
              row.mode === modeByLabel.mode &&
              row.index === Number(numbered[1]) &&
              row.status === 'pending',
          )
        : rows.find((row) => modeLabel(row.mode) === failure.label && row.status === 'pending');
    if (target !== undefined) {
      target.status = 'failed';
      target.reason = failure.reason;
    }
  }
  const running = rows.find((row) => row.status === 'pending');
  if (
    running !== undefined &&
    stageText !== '' &&
    stageText.startsWith(`${running.label}·`)
  ) {
    running.status = 'running';
  }
  return rows;
}

const FAIL_COLOR = tokens.colorError;

export function PlanQueue({
  batch,
  spec = null,
}: {
  batch: PlanBatch;
  spec?: BatchSpec | null;
}): React.ReactElement {
  const [tracesOpen, setTracesOpen] = useState(false);
  const batchPlans =
    batch.batchId === null
      ? []
      : batch.plans.filter(
          (p) => p.batch_id !== null && p.batch_id !== undefined && p.batch_id === batch.batchId,
        );
  const failures = parseFailures(batch.failDetail);
  const rows = spec !== null ? buildQueueRows(spec, batch.plans, batch.batchId, batch.failDetail, batch.stageText) : [];
  const doneCount = batchPlans.length;
  return (
    <PageSection title="② 规划队列" dense>
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
        {spec !== null
          ? rows.map((row) =>
              row.status === 'done' && row.plan !== undefined ? (
                <DoneRow key={`${row.mode}#${String(row.index)}`} plan={row.plan} />
              ) : (
                <ThinRow
                  key={`${row.mode}#${String(row.index)}`}
                  label={`${modeLabel(row.mode)} · 第${String(row.index)}条`}
                  status={row.status}
                  reason={row.reason}
                  onTrace={
                    row.status === 'failed'
                      ? () => {
                          setTracesOpen(true);
                        }
                      : undefined
                  }
                />
              ),
            )
          : [
              ...batchPlans.map((plan) => <DoneRow key={plan.id} plan={plan} />),
              ...failures.map((failure, index) => (
                <ThinRow
                  key={`f${String(index)}`}
                  label={`${failure.label} · ${failure.slot}`}
                  status="failed"
                  reason={failure.reason}
                  onTrace={() => {
                    setTracesOpen(true);
                  }}
                />
              )),
              batch.stageText !== '' && (
                <ThinRow key="stage" label={batch.stageText} status="running" />
              ),
            ]}
        {spec !== null && spec.modes.length > 0 && (
          <Alert
            style={{ marginTop: tokens.spaceMd }}
            type="info"
            showIcon
            title={`本批共 ${String(spec.modes.length * spec.k)} 条：完成 ${String(doneCount)} 条，剩余 ${String(
              Math.max(0, spec.modes.length * spec.k - doneCount),
            )} 条`}
          />
        )}
      </div>
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

function ThinRow({
  label,
  status,
  reason,
  onTrace,
}: {
  label: string;
  status: RowStatus;
  reason?: string;
  onTrace?: () => void;
}): React.ReactElement {
  const meta: Record<RowStatus, { text: string; color: string }> = {
    pending: { text: '排队', color: tokens.textTertiary },
    running: { text: '生成中', color: tokens.colorInfo },
    done: { text: '完成', color: tokens.colorSuccess },
    failed: { text: '失败', color: tokens.colorError },
  };
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
      <span style={{ width: 6, height: 6, borderRadius: tokens.radiusDot, background: meta[status].color, flexShrink: 0 }} />
      <span style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, color: tokens.textPrimary }}>
        {label}
      </span>
      {status === 'failed' && reason !== undefined && (
        <span
          style={{
            fontSize: tokens.text.badge.size,
            color: meta[status].color,
            minWidth: 0,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          title={reason}
        >
          {reason}
        </span>
      )}
      {onTrace !== undefined && (
        <Button size="small" type="text" style={{ marginLeft: 'auto', flexShrink: 0 }} onClick={onTrace}>
          往返
        </Button>
      )}
      <span
        style={{
          marginLeft: 'auto',
          flexShrink: 0,
          fontSize: tokens.text.badge.size,
          lineHeight: tokens.text.badge.leading,
          color: meta[status].color,
        }}
      >
        {meta[status].text}
      </span>
    </div>
  );
}
