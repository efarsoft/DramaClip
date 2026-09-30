/** 只读方案卡（规格 §4.3 四要素 + 重叠率）：用户不挑角度，只判断「K 条是不是 K 个卖点」。
 *  挑方案列表与规划队列共用——队列里完成的行就是这张卡的实时形态。
 *  另带排期预估（时间轴画面窗之和）与文案全文查看（旁白逐段拼读）。 */
import { Button, Card, Modal, Tag } from 'antd';
import { useState, type ReactElement } from 'react';
import type { NarrationPlan } from '@dramaclip/protocol';
import { modeLabel } from '../../components/modeMeta';
import { tokens } from '../../styles/theme';
import { planCardView } from './planCards';

/** 成片时长预估（秒）：有旁白按 字数/4.2（与服务端 estimate_duration 同一口径，
 *  回填后段长=实测音频≈此数）；纯原片没有旁白，画面窗即成片。
 *  之前用画面窗合计，跨集剧本的画面窗是转写跨度，会高估两倍以上。 */
const CHARS_PER_SECOND = 4.2;

export function estimatedDurationS(plan: NarrationPlan): number {
  const texts = plan.plan_data.narration_texts ?? [];
  if (texts.length === 0) {
    return plan.plan_data.timeline.reduce((sum, seg) => sum + (seg.end - seg.start), 0);
  }
  return texts.reduce((sum, item) => sum + (item.text?.length ?? 0), 0) / CHARS_PER_SECOND;
}

export function formatDuration(seconds: number): string {
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes === 0) return `${String(rest)} 秒`;
  if (rest === 0) return `${String(minutes)} 分钟`;
  return `${String(minutes)} 分 ${String(rest)} 秒`;
}

export function PlanCard({
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
  const [copyOpen, setCopyOpen] = useState(false);
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
          <span>预计 {formatDuration(estimatedDurationS(plan))}</span>
          <span>{card.overlap}</span>
          {card.dropped !== '' && (
            <span style={{ color: tokens.colorWarning }}>{card.dropped}</span>
          )}
          <PlanCopyButton plan={plan} />
        </span>
      </div>
      <PlanCopyModal plan={plan} open={copyOpen} onClose={() => setCopyOpen(false)} />
    </Card>
  );
}

/** 文案全文查看：旁白逐段拼读（段 id 只给运维对账用，正文不打扰阅读）。 */
function PlanCopyButton({ plan }: { plan: NarrationPlan }): ReactElement {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        size="small"
        type="text"
        style={{ marginLeft: 'auto', padding: 0 }}
        onClick={(event) => {
          event.stopPropagation();
          setOpen(true);
        }}
      >
        文案
      </Button>
      <PlanCopyModal plan={plan} open={open} onClose={() => setOpen(false)} />
    </>
  );
}

function PlanCopyModal({ plan, open, onClose }: { plan: NarrationPlan; open: boolean; onClose: () => void }): ReactElement {
  const copy = plan.plan_data.narration_texts.map((item) => item.text).join('\n\n');
  return (
    <Modal
      title="完整文案"
      open={open}
      onCancel={onClose}
      footer={null}
      width={680}
      styles={{ body: { maxHeight: '60vh', overflow: 'auto' } }}
    >
      <pre
        style={{
          margin: 0,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-all',
          fontSize: tokens.text.body.size,
          lineHeight: tokens.text.body.leading,
          color: tokens.textPrimary,
        }}
      >
        {copy}
      </pre>
    </Modal>
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
