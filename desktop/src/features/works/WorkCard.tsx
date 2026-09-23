/** 成品卡（卷三图5 目标形态）：逐片封面 + 角度名（金）+ 模式/取材/时间 + 四项自检徽章 + 动作行。
 *
 * 徽章三态是三种视觉（意见08）：✓ 实底绿 / ✕ 红底可看度量原文 / — 灰描边空心。
 * 「—」绝不是绿勾的另一种画法——量不到就是量不到。
 */
import type { CSSProperties, ReactElement } from 'react';
import { Button, Checkbox, Tag, Tooltip } from 'antd';
import { PlayCircleOutlined } from '@ant-design/icons';
import type { WorkItem } from '@dramaclip/protocol';
import { modeLabel } from '../../components/modeMeta';
import { mediaUrl } from '../../services/client';
import { layout, tokens } from '../../styles/theme';
import {
  durationLabel,
  episodeLabel,
  formatSize,
  formatWhen,
  modeColor,
  selfCheckBadges,
  type SelfCheckBadge,
} from './worksView';

export interface WorkCardActions {
  readonly onOpen: () => void;
  readonly onPreview: () => void;
  readonly onJumpPlan: () => void;
  readonly onFolder: () => void;
  readonly onToggleSelect: () => void;
}

export function WorkCard({
  work,
  projectCover,
  selected,
  actions,
}: {
  work: WorkItem;
  projectCover?: string;
  selected: boolean;
  actions: WorkCardActions;
}): ReactElement {
  return (
    <div
      onClick={actions.onOpen}
      style={{
        background: tokens.bgContainer,
        border: `1px solid ${selected ? tokens.colorPrimary : tokens.borderSecondary}`,
        borderRadius: tokens.radiusCard,
        overflow: 'hidden',
        cursor: 'pointer',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <WorkPoster work={work} cover={work.cover_path ?? projectCover} selected={selected} onToggleSelect={actions.onToggleSelect} />
      <CardBody work={work} actions={actions} />
    </div>
  );
}

/** 卡身：角度名（金）+ 右对齐 mono「时长 · 体积」+ meta 行 + 徽章 + 动作行。 */
function CardBody({ work, actions }: { work: WorkItem; actions: WorkCardActions }): ReactElement {
  const metaLine = [
    modeLabel(work.narration_mode),
    episodeLabel(work.episode_ids),
    formatWhen(work.completed_at),
  ]
    .filter((part) => part !== '')
    .join(' · ');
  return (
    <div
      style={{
        padding: `${tokens.spaceSm} ${tokens.spaceMd} ${tokens.spaceMd}`,
        display: 'flex',
        flexDirection: 'column',
        gap: tokens.spaceXs,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm }}>
        <AngleName work={work} />
        <span
          style={{
            marginLeft: 'auto',
            fontFamily: tokens.fontFamilyMono,
            fontSize: tokens.text.badge.size,
            lineHeight: tokens.text.badge.leading,
            color: tokens.textTertiary,
            flexShrink: 0,
          }}
        >
          {`${durationLabel(work.duration_s) || '—'} · ${formatSize(work.size_bytes)}`}
        </span>
      </div>
      <span
        style={{
          fontSize: tokens.text.badge.size,
          lineHeight: tokens.text.badge.leading,
          color: tokens.textTertiary,
        }}
      >
        {metaLine}
      </span>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: tokens.spaceXs }}>
        {selfCheckBadges(work.selfcheck).map((badge) => (
          <SelfCheckChip key={badge.key} badge={badge} />
        ))}
      </div>
      <CardActionRow work={work} actions={actions} />
    </div>
  );
}

/** 角度名（金）：与方案卡同款 Tag color="gold"；无角度（原声模式/方案已删）退到模式名。 */
function AngleName({ work }: { work: WorkItem }): ReactElement {
  if (work.angle !== null && work.angle !== undefined && work.angle !== '') {
    return <Tag color="gold" style={{ marginRight: 0 }}>{work.angle}</Tag>;
  }
  return (
    <strong
      style={{
        color: tokens.textPrimary,
        fontSize: tokens.text.meta.size,
        lineHeight: tokens.text.meta.leading,
        fontWeight: tokens.text.body.weightActive,
      }}
    >
      {modeLabel(work.narration_mode)}
    </strong>
  );
}

/** 封面：9/12 竖幅（图5），逐片 cover_path 优先；左上模式角标、右下 mono 时长、右上勾选。 */
function WorkPoster({
  work,
  cover,
  selected,
  onToggleSelect,
}: {
  work: WorkItem;
  cover?: string;
  selected: boolean;
  onToggleSelect: () => void;
}): ReactElement {
  return (
    <div
      className="work-poster"
      style={{ position: 'relative', aspectRatio: '9 / 12', background: tokens.posterBase }}
    >
      <PosterArt cover={cover} mode={work.narration_mode} />
      <span style={{ position: 'absolute', inset: 0, background: tokens.posterScrim }} />
      <span style={{ ...posterChipBase(), left: 6, top: 6, background: tokens.posterCaption, color: tokens.colorWhite }}>
        {modeLabel(work.narration_mode)}
      </span>
      <span
        style={{
          ...posterChipBase(),
          right: 6,
          bottom: 6,
          background: tokens.posterCaption,
          color: tokens.colorWhite,
          fontFamily: tokens.fontFamilyMono,
        }}
      >
        {durationLabel(work.duration_s) || '—'}
      </span>
      <SelectPlate selected={selected} onToggleSelect={onToggleSelect} />
    </div>
  );
}

function PosterArt({ cover, mode }: { cover?: string; mode?: string }): ReactElement {
  if (cover !== undefined && cover !== '') {
    return (
      <img
        src={mediaUrl(cover)}
        alt=""
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }}
      />
    );
  }
  return (
    <PlayCircleOutlined
      style={{
        fontSize: tokens.glyph.poster,
        color: modeColor(mode),
        position: 'absolute',
        inset: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    />
  );
}

/** 勾选底板：深色 posterPlate 托底保证海报上可见；点击不冒泡到卡片的「打开详情」。 */
function SelectPlate({ selected, onToggleSelect }: { selected: boolean; onToggleSelect: () => void }): ReactElement {
  return (
    <span
      onClick={(event) => {
        event.stopPropagation();
      }}
      style={{
        position: 'absolute',
        right: 6,
        top: 6,
        background: tokens.posterPlate,
        borderRadius: tokens.radiusThumb,
        display: 'flex',
        padding: `${String(layout.posterChip.paddingBlock)}px ${String(layout.posterChip.paddingInline)}px`,
      }}
    >
      <Checkbox checked={selected} onChange={onToggleSelect} aria-label="选择这条成片" />
    </span>
  );
}

function posterChipBase(): CSSProperties {
  return {
    position: 'absolute',
    fontSize: tokens.text.badge.size,
    lineHeight: tokens.text.badge.leading,
    padding: `${String(layout.posterChip.paddingBlock)}px ${String(layout.posterChip.paddingInline)}px`,
    borderRadius: tokens.radiusChip,
  };
}

/** 单项自检徽章：三态三种视觉，tooltip 里是度量原文（不截断）。 */
export function SelfCheckChip({ badge }: { badge: SelfCheckBadge }): ReactElement {
  return (
    <Tooltip title={badge.detail}>
      <span style={chipStyle(badge.tone)}>{badge.text}</span>
    </Tooltip>
  );
}

function chipStyle(tone: SelfCheckBadge['tone']): CSSProperties {
  const base: CSSProperties = {
    fontSize: tokens.text.badge.size,
    lineHeight: tokens.text.badge.leading,
    padding: `${String(layout.posterChip.paddingBlock)}px ${String(layout.posterChip.paddingInline)}px`,
    borderRadius: tokens.radiusChip,
    display: 'inline-flex',
    alignItems: 'center',
  };
  if (tone === 'ok') {
    return { ...base, background: tokens.colorSuccess, color: tokens.bgSidebar };
  }
  if (tone === 'fail') {
    return { ...base, background: tokens.errorSoft, color: tokens.colorError, border: `1px solid ${tokens.colorError}` };
  }
  // — 灰描边空心：与实底绿勾明确区分（意见08）
  return { ...base, background: 'transparent', color: tokens.textTertiary, border: `1px solid ${tokens.borderSecondary}` };
}

function CardActionRow({ work, actions }: { work: WorkItem; actions: WorkCardActions }): ReactElement {
  const stop = (run: () => void) => (event: React.MouseEvent): void => {
    event.stopPropagation();
    run();
  };
  const hasPlan = work.narration_plan_id !== null && work.narration_plan_id !== undefined && work.narration_plan_id !== '';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceXs }}>
      <Button size="small" onClick={stop(actions.onPreview)}>
        预览
      </Button>
      <Tooltip title={hasPlan ? '' : '方案已删除，追溯链断'}>
        <Button size="small" disabled={!hasPlan} onClick={stop(actions.onJumpPlan)}>
          方案卡
        </Button>
      </Tooltip>
      <Button size="small" style={{ marginLeft: 'auto' }} onClick={stop(actions.onFolder)}>
        打开所在文件夹
      </Button>
    </div>
  );
}
