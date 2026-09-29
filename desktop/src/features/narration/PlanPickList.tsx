/** 阶段②（规格 §6 的 ④）：只读方案卡 → 勾选 → 开始出片；卡头覆盖度行常驻（静默清单第 2 条），
 * 底栏成本预估一期口径（意见08）：条数 + 磁盘（估），耗时/LLM 没有实测口径就是「—」。 */
import { Alert, Button, Card, Empty, Tag, Tooltip } from 'antd';
import { useEffect, useState, type ReactElement } from 'react';
import { PageSection } from '../../components/layout/PageKit';
import type { NarrationPlan } from '@dramaclip/protocol';
import { modeLabel } from '../../components/modeMeta';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';
import { planCardView, recommendedIds } from './planCards';
import { coverageOf, estimateDisk, type Coverage } from './produceView';
import type { ExportQueue } from './useExportQueue';
import type { PlanBatch } from './usePlanBatch';

const NO_METRIC_TIP = '暂无渲染侧实测口径——预估错了是噪音，不预估是诚实（意见08）';
const monoSpan: React.CSSProperties = { fontFamily: tokens.fontFamilyMono };

export function PlanPickList({
  batch,
  queue,
  episodeCount,
  avgBytes,
}: {
  batch: PlanBatch;
  queue: ExportQueue;
  /** 全剧集数（覆盖度行的分母）；拿不到传 0，覆盖度行缺席而不是显示 0/0。 */
  episodeCount: number;
  /** 本剧已完成成片的实测均值字节（磁盘预估系数）；null = 无实测口径。 */
  avgBytes: number | null;
}) {
  const [picked, setPicked] = useState<string[]>([]);
  const [recommended, setRecommended] = useState<string[]>([]);
  const plans = batch.plans;

  // 默认推荐：每模式勾 2 条（有评分取前两名，无分取批次前两个可出片）——不用盲选
  useEffect(() => {
    const ids = recommendedIds(plans);
    setRecommended(ids);
    setPicked(ids);
  }, [plans]);

  if (plans.length === 0) {
    return <NoPlansSection planning={batch.planning} />;
  }

  const coverage = coverageOf(plans, episodeCount);
  const disk = estimateDisk(picked.length, avgBytes);
  return (
    <PageSection
      title="② 挑方案，去出片"
      dense
      extra={coverage === null ? undefined : <CoverageChip coverage={coverage} />}
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: tokens.spaceMd }}>
        {plans.map((plan) => (
          <PlanCard
            key={plan.id}
            plan={plan}
            recommended={recommended.includes(plan.id)}
            checked={picked.includes(plan.id)}
            onToggle={() => {
              setPicked((prev) => (prev.includes(plan.id) ? prev.filter((id) => id !== plan.id) : [...prev, plan.id]));
            }}
          />
        ))}
      </div>
      <ProduceBar
        count={picked.length}
        total={plans.length}
        submitting={queue.submitting}
        diskGb={disk.diskGb}
        diskSource={disk.source}
        rejected={queue.rejected.map((item) => `${modeLabel(planMode(plans, item.plan_id))}—${item.reason}`)}
        error={queue.error}
        onProduce={() => {
          void queue.run(picked);
        }}
      />
    </PageSection>
  );
}

/** 还没有方案：区分「正在产出」与「还没点生成」两种空，不混成一句话。 */
function NoPlansSection({ planning }: { planning: boolean }): React.ReactElement {
  return (
    <PageSection title="② 挑方案，去出片" dense>
      <Empty
        description={planning ? '方案正在一条条产出' : '选好模式、定每个模式几条，点「生成方案」'}
        styles={{ image: { height: 60 } }}
      />
    </PageSection>
  );
}

/** 覆盖度行（常驻卡头）：n = 本批方案取材集合并计数（同一集只算一次），m = 全剧集数——数字单独 mono span。 */
function CoverageChip({ coverage }: { coverage: Coverage }): React.ReactElement {
  return (
    <span
      style={{
        ...mixins.chip(),
        background: tokens.successSoft,
        color: tokens.colorSuccess,
        flexShrink: 0,
      }}
    >
      本次规划覆盖 <span style={monoSpan}>{`${String(coverage.covered)}/${String(coverage.total)}`}</span> 集
    </span>
  );
}

/** 底栏（图4）：成本预估四芯片 + 唯一 primary「开始出片」；被拒与失败原文照旧上屏。 */
function ProduceBar({
  count,
  total,
  submitting,
  diskGb,
  diskSource,
  rejected,
  error,
  onProduce,
}: {
  count: number;
  total: number;
  submitting: boolean;
  diskGb: string | null;
  diskSource: string;
  rejected: string[];
  error: string;
  onProduce: () => void;
}) {
  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', marginTop: tokens.spaceLg, gap: tokens.spaceMd, flexWrap: 'wrap' }}>
        <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>
          已选 {String(count)} / {String(total)} 条方案
        </span>
        <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>
          成本预估
        </span>
        <CostChip label="成片" value={`${String(count)} 条`} dim={false} tooltip="" />
        <CostChip label="磁盘" value={diskGb ?? '—'} dim={diskGb === null} tooltip={diskSource} />
        <CostChip label="耗时" value="—" dim tooltip={NO_METRIC_TIP} />
        <CostChip label="LLM 成稿" value="—" dim tooltip={NO_METRIC_TIP} />
        <Button type="primary" style={{ marginLeft: 'auto' }} disabled={count === 0} loading={submitting} onClick={onProduce}>
          开始出片
        </Button>
      </div>
      {rejected.length > 0 && (
        <Alert style={{ marginTop: tokens.spaceMd }} type="warning" showIcon title={`未进入出片队列 ${String(rejected.length)} 条：${rejected.join('；')}`} />
      )}
      {error !== '' && <Alert style={{ marginTop: tokens.spaceMd }} type="error" showIcon title={error} />}
    </>
  );
}

function CostChip({ label, value, dim, tooltip }: { label: string; value: string; dim: boolean; tooltip: string }) {
  const chip = (
    <span
      style={{
        ...mixins.chip(),
        color: dim ? tokens.textTertiary : tokens.textSecondary,
        flexShrink: 0,
      }}
    >
      {label} <span style={monoSpan}>{value}</span>
    </span>
  );
  return tooltip === '' ? chip : <Tooltip title={tooltip}>{chip}</Tooltip>;
}

/** 被拒的是哪条方案，界面上只有模式名可读——id 对用户没有意义。 */
function planMode(plans: NarrationPlan[], planId: string): string {
  return plans.find((plan) => plan.id === planId)?.narration_mode ?? '';
}

/** 只读方案卡（规格 §4.3 四要素 + 重叠率）：用户不挑角度，只判断「K 条是不是 K 个卖点」。 */
function PlanCard({
  plan,
  checked,
  recommended,
  onToggle,
}: {
  plan: NarrationPlan;
  checked: boolean;
  recommended: boolean;
  onToggle: () => void;
}) {
  const card = planCardView(plan);
  return (
    <Card
      size="small"
      hoverable={card.pickable}
      onClick={() => {
        if (card.pickable) onToggle();
      }}
      style={{
        borderColor: checked ? tokens.colorPrimary : tokens.border,
        background: checked ? tokens.accentSoft : undefined,
        opacity: card.pickable ? 1 : 0.55,
        cursor: card.pickable ? 'pointer' : 'not-allowed',
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm, minHeight: 130 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm, flexWrap: 'wrap' }}>
          {card.angle === '' ? (
            <strong style={{ color: tokens.textPrimary, fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading }}>{modeLabel(card.mode)}</strong>
          ) : (
            <>
              <Tag color="gold" style={{ marginRight: 0 }}>
                {card.angle}
              </Tag>
              <strong style={{ color: tokens.textPrimary, fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading }}>{modeLabel(card.mode)}</strong>
            </>
          )}
          <CardBadges recommended={recommended} checked={checked} pickable={card.pickable} />
        </div>
        {card.hook !== '' && <span style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, color: tokens.textPrimary }}>{card.hook}</span>}
        {card.reason !== '' && <span style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, color: tokens.textSecondary }}>{card.reason}</span>}
        {card.gate !== '' && (
          <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.colorWarning }}>{card.gate}</span>
        )}
        <span style={{ display: 'flex', gap: tokens.spaceMd, marginTop: 'auto', fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
          <span>{modeLabel(card.mode)}</span>
          <span>{card.episodes}</span>
          <span>{card.overlap}</span>
          {card.dropped !== '' && (
            <span style={{ color: tokens.colorWarning }}>{card.dropped}</span>
          )}
        </span>
      </div>
    </Card>
  );
}

function CardBadges({
  recommended,
  checked,
  pickable,
}: {
  recommended: boolean;
  checked: boolean;
  pickable: boolean;
}): ReactElement {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: tokens.spaceSm, marginLeft: 'auto' }}>
      {recommended && (
        <Tag color="gold" style={{ marginRight: 0 }}>
          推荐
        </Tag>
      )}
      {checked && (
        <Tag color="blue" style={{ marginLeft: 'auto', marginRight: 0 }}>
          已选
        </Tag>
      )}
      {!pickable && (
        <Tag color="warning" style={{ marginRight: 0 }}>
          不能出片
        </Tag>
      )}
    </span>
  );
}
