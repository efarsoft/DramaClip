/** 转写卡片：分段文本可点击定位、行内编辑（清空回车删段）。 */
import { Button, Card } from 'antd';
import { useState } from 'react';
import type { AsrSegment } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';

export function TranscriptCard({
  segments,
  resyncing,
  onSeek,
  onSaveEdit,
  onResync,
}: {
  segments: readonly AsrSegment[];
  resyncing: boolean;
  onSeek: (seconds: number) => void;
  onSaveEdit: (index: number, text: string) => void;
  onResync: () => void;
}): React.ReactElement {
  return (
    <Card
      size="small"
      title="ASR 转写（点击文本修正；清空回车删除该段）"
      extra={
        <Button size="small" loading={resyncing} onClick={onResync}>
          重跑语义
        </Button>
      }
    >
      {segments.length === 0 ? (
        <span style={{ fontSize: 12.5, color: tokens.textTertiary }}>尚未转写</span>
      ) : (
        <div
          style={{
            maxHeight: 260,
            overflowY: 'auto',
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
          }}
        >
          {segments.map((segment, index) => (
            <SegmentRow
              key={`${String(segment.start)}-${String(index)}`}
              segment={segment}
              index={index}
              onSeek={onSeek}
              onSaveEdit={onSaveEdit}
            />
          ))}
        </div>
      )}
    </Card>
  );
}

const INPUT_STYLE = {
  flex: 1,
  borderRadius: 6,
  border: `1px solid ${tokens.colorPrimary}`,
  background: tokens.bgInput,
  color: tokens.textPrimary,
  fontSize: 12.5,
  padding: '3px 8px',
  outline: 'none',
} as const;

function SegmentRow({
  segment,
  index,
  onSeek,
  onSaveEdit,
}: {
  segment: AsrSegment;
  index: number;
  onSeek: (seconds: number) => void;
  onSaveEdit: (index: number, text: string) => void;
}): React.ReactElement {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');

  if (!editing) {
    return (
      <div style={{ display: 'flex', gap: 10, fontSize: 12.5, alignItems: 'baseline' }}>
        <SeekButton seconds={segment.start} onSeek={onSeek} />
        <span style={{ fontFamily: tokens.fontFamilyMono, fontSize: 11, color: tokens.textTertiary, flexShrink: 0 }}>
          -{formatClock(segment.end)}
        </span>
        <span
          style={{ color: tokens.textPrimary, cursor: 'text' }}
          onClick={() => {
            setDraft(segment.text);
            setEditing(true);
          }}
        >
          {segment.text}
        </span>
      </div>
    );
  }
  return (
    <div style={{ display: 'flex', gap: 8 }}>
      <input
        value={draft}
        autoFocus
        style={INPUT_STYLE}
        onChange={(event) => {
          setDraft(event.target.value);
        }}
        onKeyDown={(event) => {
          if (event.key !== 'Enter') return;
          onSaveEdit(index, draft.trim());
          setEditing(false);
        }}
        onBlur={() => {
          setEditing(false);
        }}
      />
    </div>
  );
}

function formatClock(seconds: number): string {
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(
    Math.floor(seconds % 60),
  ).padStart(2, '0')}`;
}

function SeekButton({
  seconds,
  onSeek,
}: {
  seconds: number;
  onSeek: (seconds: number) => void;
}): React.ReactElement {
  const text = formatClock(seconds);
  return (
    <button
      type="button"
      onClick={() => {
        onSeek(seconds);
      }}
      style={{
        background: 'none',
        border: 'none',
        color: tokens.textTertiary,
        fontFamily: tokens.fontFamilyMono,
        fontSize: 11,
        cursor: 'pointer',
        padding: 0,
        flexShrink: 0,
      }}
    >
      {text}
    </button>
  );
}
