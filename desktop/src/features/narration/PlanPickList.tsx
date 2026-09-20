/** 阶段②（规格 §6 的 ④）：只读方案卡 → 勾选 → 出片，并显示队列进度与被拒原因。 */
import { Alert, Button, Card, Empty, Tag } from 'antd';
import { useEffect, useState } from 'react';
import { PageSection } from '../../components/layout/PageKit';
import type { NarrationPlan } from '@dramaclip/protocol';
import { modeLabel } from '../../components/modeMeta';
import { tokens } from '../../styles/theme';
import { planCardView } from './planCards';
import type { ExportQueue } from './useExportQueue';
import type { PlanBatch } from './usePlanBatch';
import { StageProgress } from './StageProgress';

export function PlanPickList({ batch, queue }: { batch: PlanBatch; queue: ExportQueue }) {
  const [picked, setPicked] = useState<string[]>([]);
  const plans = batch.plans;

  // 换了一批方案，上一批的勾选 id 在这一批里根本不存在——不清空就会把过期 id 提交去渲染
  useEffect(() => {
    setPicked([]);
  }, [plans]);

  if (plans.length === 0) {
    return (
      <PageSection title="② 挑方案，去出片" dense>
        <Empty
          description={batch.planning ? '方案正在一条条产出' : '选好模式、定每个模式几条，点「生成方案」'}
          styles={{ image: { height: 60 } }}
        />
      </PageSection>
    );
  }

  return (
    <PageSection title="② 挑方案，去出片" dense>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: tokens.spaceMd }}>
        {plans.map((plan) => (
          <PlanCard
            key={plan.id}
            plan={plan}
            checked={picked.includes(plan.id)}
            onToggle={() => {
              setPicked((prev) => (prev.includes(plan.id) ? prev.filter((id) => id !== plan.id) : [...prev, plan.id]));
            }}
          />
        ))}
      </div>
      <QueueFooter
        count={picked.length}
        total={plans.length}
        running={queue.running}
        percent={queue.percent}
        stageText={queue.stageText}
        rejected={queue.rejected.map((item) => `${modeLabel(planMode(plans, item.plan_id))}—${item.reason}`)}
        error={queue.error}
        onProduce={() => {
          void queue.run(picked);
        }}
      />
    </PageSection>
  );
}

function QueueFooter({
  count,
  total,
  running,
  percent,
  stageText,
  rejected,
  error,
  onProduce,
}: {
  count: number;
  total: number;
  running: boolean;
  percent: number;
  stageText: string;
  rejected: string[];
  error: string;
  onProduce: () => void;
}) {
  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', marginTop: tokens.spaceLg }}>
        <span style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary }}>
          已选 {String(count)} / {String(total)} 条方案
        </span>
        <Button type="primary" style={{ marginLeft: 'auto' }} disabled={count === 0} loading={running} onClick={onProduce}>
          {running ? '出片中…' : '出片所选'}
        </Button>
      </div>
      {running && <StageProgress percent={percent} stageText={stageText} />}
      {rejected.length > 0 && (
        <Alert style={{ marginTop: tokens.spaceMd }} type="warning" showIcon title={`未进入出片队列 ${String(rejected.length)} 条：${rejected.join('；')}`} />
      )}
      {error !== '' && <Alert style={{ marginTop: tokens.spaceMd }} type="error" showIcon title={error} />}
    </>
  );
}

/** 被拒的是哪条方案，界面上只有模式名可读——id 对用户没有意义。 */
function planMode(plans: NarrationPlan[], planId: string): string {
  return plans.find((plan) => plan.id === planId)?.narration_mode ?? '';
}

/** 只读方案卡（规格 §4.3 四要素 + 重叠率）：用户不挑角度，只判断「K 条是不是 K 个卖点」。 */
function PlanCard({ plan, checked, onToggle }: { plan: NarrationPlan; checked: boolean; onToggle: () => void }) {
  const card = planCardView(plan);
  return (
    <Card size="small" hoverable onClick={onToggle} style={{ borderColor: checked ? tokens.colorPrimary : tokens.border, background: checked ? tokens.accentSoft : undefined }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm, minHeight: 130 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm, flexWrap: 'wrap' }}>
          {card.angle === '' ? (
            <strong style={{ color: tokens.textPrimary, fontSize: tokens.fontBody }}>{modeLabel(card.mode)}</strong>
          ) : (
            <Tag color="gold" style={{ marginRight: 0 }}>
              {card.angle}
            </Tag>
          )}
          {checked && (
            <Tag color="blue" style={{ marginLeft: 'auto', marginRight: 0 }}>
              已选
            </Tag>
          )}
        </div>
        {card.hook !== '' && <span style={{ fontSize: tokens.fontBody, color: tokens.textPrimary }}>{card.hook}</span>}
        {card.reason !== '' && <span style={{ fontSize: tokens.fontCaption, color: tokens.textSecondary }}>{card.reason}</span>}
        <span style={{ display: 'flex', gap: tokens.spaceMd, marginTop: 'auto', fontSize: tokens.fontMicro, color: tokens.textTertiary }}>
          <span>{modeLabel(card.mode)}</span>
          <span>{card.episodes}</span>
          <span>{card.overlap}</span>
        </span>
      </div>
    </Card>
  );
}
