/** 素材列表行：封面缩略 + 文件名 + 状态，可拖拽排序、单击激活、勾选批量。 */
import { Checkbox } from 'antd';
import type { Episode } from '@dramaclip/protocol';
import { mediaUrl } from '../../services/client';
import { tokens } from '../../styles/theme';

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
  const asrOk = episode.status === 'done';
  return (
    <DragShell
      active={active}
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
        <RowMeta duration={episode.duration ?? 0} asrOk={asrOk} highlightCount={highlightCount} />
      </span>
      <MoveButtons onMove={onMove} />
    </DragShell>
  );
}

function DragShell({
  active,
  dropTarget,
  children,
  onDragStart,
  onDragOver,
  onDrop,
  onActivate,
}: {
  active: boolean;
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
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '6px 10px',
        cursor: 'grab',
        borderLeft: active ? `3px solid ${tokens.colorPrimary}` : '3px solid transparent',
        borderTop: dropTarget ? `2px solid ${tokens.colorPrimary}` : '2px solid transparent',
        background: active ? tokens.accentSoft : 'transparent',
      }}
      onMouseEnter={(event) => {
        if (!active) event.currentTarget.style.background = tokens.bgElevated;
      }}
      onMouseLeave={(event) => {
        if (!active) event.currentTarget.style.background = 'transparent';
      }}
    >
      {children}
    </div>
  );
}

function RowName({ episode, active }: { episode: Episode; active: boolean }): React.ReactElement {
  return (
    <span
      title={episode.name}
      style={{
        fontSize: 12.5,
        fontWeight: 600,
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
      <MoveButton label="▲" direction={-1} onMove={onMove} />
      <MoveButton label="▼" direction={1} onMove={onMove} />
    </span>
  );
}

function RowThumb({ episode }: { episode: Episode }): React.ReactElement {
  return episode.cover_path !== undefined ? (
    <img
      src={mediaUrl(episode.cover_path)}
      alt=""
      style={{ width: 34, height: 46, objectFit: 'cover', borderRadius: 4, flexShrink: 0 }}
    />
  ) : (
    <span
      style={{
        width: 34,
        height: 46,
        borderRadius: 4,
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: 13,
        color: tokens.textTertiary,
        background: `${tokens.colorPrimary}1A`,
      }}
    >
      ▶
    </span>
  );
}

function MoveButton({
  label,
  direction,
  onMove,
}: {
  label: string;
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
        width: 18,
        height: 13,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: 8,
        lineHeight: 1,
        borderRadius: 3,
        border: `1px solid ${tokens.border}`,
        background: 'transparent',
        color: tokens.textTertiary,
        cursor: 'pointer',
      }}
    >
      {label}
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
      style={{ marginRight: 2 }}
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
  asrOk,
  highlightCount,
}: {
  duration: number;
  asrOk: boolean;
  highlightCount: number;
}): React.ReactElement {
  return (
    <span style={{ fontSize: 11, color: tokens.textTertiary, display: 'flex', gap: 8 }}>
      <span>{Math.round(duration)}s</span>
      <span style={{ color: asrOk ? tokens.colorSuccess : tokens.textTertiary }}>
        ● {asrOk ? '已转写' : '待分析'}
      </span>
      {highlightCount > 0 && (
        <span style={{ color: tokens.colorWarning }}>高光 {String(highlightCount)}</span>
      )}
    </span>
  );
}
