/** 素材列表行：封面缩略 + 文件名 + 状态，可拖拽排序、单击激活、勾选批量。 */
import { Checkbox } from 'antd';
import { DownOutlined, PlayCircleFilled, UpOutlined } from '@ant-design/icons';
import type { Episode } from '@dramaclip/protocol';
import { mediaUrl } from '../../services/client';
import { hoverBg, mixins } from '../../styles/mixins';
import { layout, tokens } from '../../styles/theme';

export function EpisodeListRow({
  episode,
  highlightCount,
  active,
  checked,
  dropTarget,
  onActivate,
  onToggle,
  onDragStart,
  onDragOver,
  onDrop,
  onMove,
}: {
  episode: Episode;
  highlightCount: number;
  active: boolean;
  checked: boolean;
  dropTarget: boolean;
  onActivate: () => void;
  onToggle: (checked: boolean) => void;
  onDragStart: () => void;
  onDragOver: () => void;
  onDrop: () => void;
  onMove: (direction: -1 | 1) => void;
}): React.ReactElement {
  return (
    <DragShell
      active={active}
      checked={checked}
      dropTarget={dropTarget}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDrop={onDrop}
      onActivate={onActivate}
    >
      <RowCheckbox checked={checked} onToggle={onToggle} />
      <RowThumb episode={episode} />
      <span style={{ display: 'flex', flexDirection: 'column', minWidth: 0, flex: 1 }}>
        <RowName episode={episode} active={active} />
        <RowMeta
          duration={episode.duration ?? 0}
          status={episode.status}
          highlightCount={highlightCount}
          hasAudio={episode.has_audio}
        />
      </span>
      <MoveButtons onMove={onMove} />
    </DragShell>
  );
}

/**
 * 行壳：三态分道（§3.2）由 mixins.listRow 承担——
 * 勾选只铺底、当前查看只画左竖条，两者不再抢同一通道。
 * dropTarget 是拖放目标提示（顶部 2px），与三态无关，故留在本地。
 */
function DragShell({
  active,
  checked,
  dropTarget,
  children,
  onDragStart,
  onDragOver,
  onDrop,
  onActivate,
}: {
  active: boolean;
  checked: boolean;
  dropTarget: boolean;
  children: React.ReactNode;
  onDragStart: () => void;
  onDragOver: () => void;
  onDrop: () => void;
  onActivate: () => void;
}): React.ReactElement {
  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDragOver={(event) => {
        event.preventDefault();
        onDragOver();
      }}
      onDrop={(event) => {
        event.preventDefault();
        onDrop();
      }}
      onClick={onActivate}
      style={{
        ...mixins.listRow({ checked, active, rows: 2 }),
        gap: tokens.spaceSm,
        cursor: 'grab',
        borderTop: dropTarget ? `2px solid ${tokens.colorPrimary}` : '2px solid transparent',
      }}
      onMouseEnter={(event) => {
        event.currentTarget.style.background = checked ? tokens.checkedSoft : hoverBg;
      }}
      onMouseLeave={(event) => {
        event.currentTarget.style.background = checked ? tokens.checkedSoft : 'transparent';
      }}
    >
      {children}
    </div>
  );
}

/** 行名：列表主行第一列，字阶最低 body（§1.2 ①）；当前查看时加主色与字重，不加底色。 */
function RowName({ episode, active }: { episode: Episode; active: boolean }): React.ReactElement {
  return (
    <span
      title={episode.name}
      style={{
        fontSize: tokens.text.body.size,
        lineHeight: tokens.text.body.leading,
        fontWeight: active ? tokens.text.body.weightActive : tokens.text.body.weight,
        color: active ? tokens.colorPrimary : tokens.textPrimary,
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
      }}
    >
      {episode.name === '' ? `第${String(episode.episode_number)}集` : episode.name}
    </span>
  );
}

function RowThumb({ episode }: { episode: Episode }): React.ReactElement {
  const frame = {
    width: tokens.glyph.thumbW,
    height: tokens.glyph.thumbH,
    borderRadius: tokens.radiusThumb,
    flexShrink: 0,
  } as const;
  // 真值判断挡掉 null/''（库内 NULL 原样过线）：没有封面走占位，绝不请求 mediaUrl(null)
  return episode.cover_path ? (
    <img
      src={mediaUrl(episode.cover_path)}
      alt=""
      style={{ ...frame, objectFit: 'cover' }}
    />
  ) : (
    <span
      style={{
        ...frame,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: tokens.colorPrimary,
        background: tokens.accentSoft,
      }}
    >
      <PlayCircleFilled style={{ fontSize: tokens.glyph.poster }} />
    </span>
  );
}

function MoveButtons({
  onMove,
}: {
  onMove: (direction: -1 | 1) => void;
}): React.ReactElement {
  return (
    <span
      style={{ display: 'flex', flexDirection: 'column', flexShrink: 0 }}
      onClick={(event) => {
        event.stopPropagation();
      }}
    >
      <MoveButton icon={<UpOutlined />} direction={-1} onMove={onMove} />
      <MoveButton icon={<DownOutlined />} direction={1} onMove={onMove} />
    </span>
  );
}

function MoveButton({
  icon,
  direction,
  onMove,
}: {
  icon: React.ReactNode;
  direction: -1 | 1;
  onMove: (direction: -1 | 1) => void;
}): React.ReactElement {
  return (
    <button
      type="button"
      title={direction === -1 ? '上移' : '下移'}
      onClick={() => {
        onMove(direction);
      }}
      style={{
        width: layout.row.moveButton.width,
        height: layout.row.moveButton.height,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 0,
        borderRadius: tokens.radiusThumb,
        border: `1px solid ${tokens.border}`,
        background: 'transparent',
        color: tokens.textTertiary,
        cursor: 'pointer',
      }}
    >
      <span style={{ fontSize: tokens.glyph.icon }}>{icon}</span>
    </button>
  );
}

function RowCheckbox({
  checked,
  onToggle,
}: {
  checked: boolean;
  onToggle: (checked: boolean) => void;
}): React.ReactElement {
  return (
    <Checkbox
      checked={checked}
      style={{ flexShrink: 0 }}
      onClick={(event) => {
        event.stopPropagation();
      }}
      onChange={(event) => {
        onToggle(event.target.checked);
      }}
    />
  );
}

function RowMeta({
  duration,
  status,
  highlightCount,
  hasAudio,
}: {
  duration: number;
  status: Episode['status'];
  highlightCount: number;
  /** null/缺省 = 未重扫的旧集（未知不告警）；false = 探测过、确实没有音频轨。 */
  hasAudio: boolean | null | undefined;
}): React.ReactElement {
  // 三态各自可辨；失败用 status/error（#F87171）——#FF4D4F 只留给钩子语义，
  // colorWarning 已被同行的「高光」计数占用，挪用会让失败与提示撞色。
  const state =
    status === 'done'
      ? { label: '已转写', color: tokens.colorSuccess }
      : status === 'failed'
        ? { label: '分析失败', color: tokens.colorError }
        : { label: '待分析', color: tokens.textTertiary };
  return (
    <span
      style={{
        fontSize: tokens.text.badge.size,
        lineHeight: tokens.text.badge.leading,
        color: tokens.textTertiary,
        display: 'flex',
        gap: tokens.spaceSm,
      }}
    >
      {/* 时长与计数是数字位：等宽（§1.3）。 */}
      <span style={{ fontFamily: tokens.fontFamilyMono }}>{Math.round(duration)}s</span>
      <span style={{ color: state.color }}>● {state.label}</span>
      {hasAudio === false && (
        <span
          style={{
            background: tokens.warningSoft,
            color: tokens.colorWarning,
            borderRadius: tokens.radiusChip,
            padding: `${String(layout.badgeChip.paddingBlock)}px ${String(layout.badgeChip.paddingInline)}px`,
          }}
        >
          无音轨
        </span>
      )}
      {highlightCount > 0 && (
        <span style={{ color: tokens.colorWarning, fontFamily: tokens.fontFamilyMono }}>
          高光 {String(highlightCount)}
        </span>
      )}
    </span>
  );
}
