/** 素材列表行：勾选批量 + 单击激活右侧详情。 */
import { Checkbox } from 'antd';
import type { Episode } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';

export function EpisodeListRow({
  episode,
  highlightCount,
  active,
  checked,
  onActivate,
  onToggle,
}: {
  episode: Episode;
  highlightCount: number;
  active: boolean;
  checked: boolean;
  onActivate: () => void;
  onToggle: (checked: boolean) => void;
}): React.ReactElement {
  const asrOk = episode.status === 'done';
  return (
    <div
      onClick={onActivate}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 12px',
        cursor: 'pointer',
        borderLeft: active ? `3px solid ${tokens.colorPrimary}` : '3px solid transparent',
        background: active ? tokens.accentSoft : 'transparent',
      }}
      onMouseEnter={(event) => {
        if (!active) event.currentTarget.style.background = tokens.bgElevated;
      }}
      onMouseLeave={(event) => {
        if (!active) event.currentTarget.style.background = 'transparent';
      }}
    >
      <RowCheckbox checked={checked} onToggle={onToggle} />
      <span style={{ display: 'flex', flexDirection: 'column', minWidth: 0, flex: 1 }}>
        <span
          style={{
            fontSize: 12.5,
            color: active ? tokens.colorPrimary : tokens.textPrimary,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {episode.name}
        </span>
        <RowMeta duration={episode.duration ?? 0} asrOk={asrOk} highlightCount={highlightCount} />
      </span>
    </div>
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
