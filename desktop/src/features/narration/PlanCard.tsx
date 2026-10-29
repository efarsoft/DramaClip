/** 只读方案卡（规格 §4.3 四要素 + 重叠率）：用户不挑角度，只判断「K 条是不是 K 个卖点」。
 *  挑方案列表与规划队列共用——队列里完成的行就是这张卡的实时形态。
 *  另带排期预估（时间轴画面窗之和）与文案全文查看（旁白逐段拼读）。 */
import { Button, Card, Modal, Tag } from 'antd';
import { useEffect, useState, type ReactElement } from 'react';
import type { AnalysisResults, NarrationPlan } from '@dramaclip/protocol';
import { analysisApi } from '../../services/client';
import { copyRowsOf } from './copyRows';
import { modeLabel } from '../../components/modeMeta';
import { tokens } from '../../styles/theme';
import { planCardView, type PlanCardView } from './planCards';

/** 成片时长预估（秒）：有旁白按 字数/4.2（与服务端 estimate_duration 同一口径，
 *  回填后段长=实测音频≈此数）；纯原片没有旁白，画面窗即成片。
 *  之前用画面窗合计，跨集剧本的画面窗是转写跨度，会高估两倍以上。 */
const CHARS_PER_SECOND = 4.2;

export function estimatedDurationS(plan: NarrationPlan): number {
  const texts = plan.plan_data.narration_texts;
  if (texts.length === 0) {
    return plan.plan_data.timeline.reduce((sum, seg) => sum + (seg.end - seg.start), 0);
  }
  return texts.reduce((sum, item) => sum + item.text.length, 0) / CHARS_PER_SECOND;
}

export function formatDuration(seconds: number): string {
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes === 0) return `${String(rest)} 秒`;
  if (rest === 0) return `${String(minutes)} 分钟`;
  return `${String(minutes)} 分 ${String(rest)} 秒`;
}

/** 源集封面与集号（音画同步·降级态）：方案卡给出「取材第几集」的画面参考。 */
interface SourceEpisode {
  cover: string | null;
  number: number;
}

export function PlanCard({
  plan,
  checked,
  recommended,
  onToggle,
  episodeCovers = {},
  onReroll,
  rerolling = false,
}: {
  plan: NarrationPlan;
  checked: boolean;
  recommended: boolean;
  onToggle: () => void;
  episodeCovers?: Record<string, SourceEpisode>;
  /** 重掷此条（规格 §1.3 补救入口）：提供才显示按钮——详情页等只读场合不传。 */
  onReroll?: () => void;
  rerolling?: boolean;
}) {
  const card = planCardView(plan);
  // 取材集如实展示全集分布（真机误读修正）；封面缩略图已移除——业主裁决：
  // 单张首集画面+集号角标传达不了取材范围，反而误导（2026-10-20）
  const materialNumbers = plan.episode_ids
    .map((id) => episodeCovers[id]?.number)
    .filter((n): n is number => typeof n === 'number')
    .sort((a, b) => a - b);
  const materialsLabel =
    materialNumbers.length === 0
      ? card.episodes
      : materialNumbers.length <= 3
        ? `取材 第${materialNumbers.map(String).join('/')}集`
        : `取材 ${String(materialNumbers.length)} 集`;
  return (
    <Card
      size="small"
      hoverable={card.pickable}
      onClick={() => {
        if (card.pickable) onToggle();
      }}
      style={{
        display: 'flex',
        flexDirection: 'row',
        gap: tokens.spaceSm,
        borderColor: checked ? tokens.colorPrimary : tokens.border,
        background: checked ? tokens.accentSoft : undefined,
        opacity: card.pickable ? 1 : 0.55,
        cursor: card.pickable ? 'pointer' : 'not-allowed',
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm, minHeight: 130, flex: 1, minWidth: 0 }}>
        <CardHeader card={card} recommended={recommended} checked={checked} onReroll={onReroll} rerolling={rerolling} />
        {card.hook !== '' && <span style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, color: tokens.textPrimary }}>{card.hook}</span>}
        {card.reason !== '' && <span style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, color: tokens.textSecondary }}>{card.reason}</span>}
        {card.gate !== '' && (
          <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.colorWarning }}>{card.gate}</span>
        )}
        <CardFooter card={card} plan={plan} materialsLabel={materialsLabel} />
      </div>
    </Card>
  );
}

/** 卡头：角度标签 + 模式名 + 推荐/已选/不可出片徽章。 */
function CardHeader({
  card,
  recommended,
  checked,
  onReroll,
  rerolling,
}: {
  card: PlanCardView;
  recommended: boolean;
  checked: boolean;
  onReroll?: () => void;
  rerolling?: boolean;
}): ReactElement {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm, flexWrap: 'wrap' }}>
      {card.angle === '' ? (
        <strong style={{ color: tokens.textPrimary, fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading }}>{modeLabel(card.mode)}</strong>
      ) : (
        <>
          <Tag color="gold" style={{ marginRight: 0 }}>
            {card.angle}
          </Tag>
          {card.arc !== '' && <Tag color="purple" style={{ marginRight: 0 }}>{card.arc}</Tag>}
          <strong style={{ color: tokens.textPrimary, fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading }}>{modeLabel(card.mode)}</strong>
        </>
      )}
      <CardBadges recommended={recommended} checked={checked} pickable={card.pickable} />
      {onReroll !== undefined && (
        <Button size="small" loading={rerolling === true} onClick={(e) => { e.stopPropagation(); onReroll(); }}>
          重掷
        </Button>
      )}
    </div>
  );
}

/** 卡脚（压底）：模式/取材/时长预估/重叠率/丢弃数 + 文案全文入口。 */
function CardFooter({
  card,
  plan,
  materialsLabel,
}: {
  card: PlanCardView;
  plan: NarrationPlan;
  materialsLabel: string;
}): ReactElement {
  return (
    <span style={{ display: 'flex', gap: tokens.spaceMd, marginTop: 'auto', fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
      <span>{modeLabel(card.mode)}</span>
      <span>{materialsLabel}</span>
      <span>预计 {formatDuration(estimatedDurationS(plan))}</span>
      <span>{card.overlap}</span>
      {card.dropped !== '' && (
        <span style={{ color: tokens.colorWarning }}>{card.dropped}</span>
      )}
      <PlanCopyButton plan={plan} />
    </span>
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
      <PlanCopyModal plan={plan} open={open} onClose={() => { setOpen(false); }} />
    </>
  );
}

function clockOf(t: number): string {
  const minutes = Math.floor(t / 60);
  const seconds = t - minutes * 60;
  return minutes > 0 ? `${String(minutes)}分${seconds.toFixed(1)}秒` : `${seconds.toFixed(1)}秒`;
}

function PlanCopyModal({ plan, open, onClose }: { plan: NarrationPlan; open: boolean; onClose: () => void }): ReactElement {
  const [results, setResults] = useState<AnalysisResults | null>(null);
  useEffect(() => {
    if (!open) {
      return;
    }
    let alive = true;
    analysisApi
      .results(plan.project_id)
      .then((r) => {
        if (alive) {
          setResults(r);
        }
      })
      .catch(() => {
        /* 分析数据取不到就退化为纯旁白视图（旧行为），弹窗不该因此报错 */
      });
    return () => {
      alive = false;
    };
  }, [open, plan.project_id]);

  const rows = results
    ? copyRowsOf(plan.plan_data, results.episodes, results.asr_segments)
    : copyRowsOf(plan.plan_data, []);

  return (
    <Modal
      title="完整文案"
      open={open}
      onCancel={onClose}
      footer={null}
      width={680}
      styles={{ body: { maxHeight: '60vh', overflow: 'auto' } }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceMd }}>
        {rows.map((row, index) => (
          <div key={index}>
            <div style={{ marginBottom: tokens.spaceXs, display: 'flex', gap: tokens.spaceSm, alignItems: 'center' }}>
              <Tag color={row.kind === 'original' ? 'gold' : 'blue'}>
                {row.kind === 'original' ? '原声' : '旁白'}
              </Tag>
              {row.episodeNumber !== null && (
                <span style={{ color: tokens.textSecondary, fontSize: tokens.text.badge.size }}>
                  第{row.episodeNumber}集 {clockOf(row.start)}-{clockOf(row.end)}
                </span>
              )}
            </div>
            <div
              style={{
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
                fontSize: tokens.text.body.size,
                lineHeight: tokens.text.body.leading,
                color: row.kind === 'original' ? tokens.textSecondary : tokens.textPrimary,
              }}
            >
              {row.text}
            </div>
          </div>
        ))}
      </div>
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
