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
        <span style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary }}>尚未转写</span>
      ) : (
        <div
          style={{
            maxHeight: 260,
            overflowY: 'auto',
            display: 'flex',
            flexDirection: 'column',
            gap: tokens.spaceSm,
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
  borderRadius: tokens.radiusThumb,
  border: `1px solid ${tokens.colorPrimary}`,
  background: tokens.bgInput,
  color: tokens.textPrimary,
  fontSize: tokens.fontCaption,
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
      <div style={{ display: 'flex', gap: tokens.spaceSm, fontSize: tokens.fontCaption, alignItems: 'baseline' }}>
        <SeekButton seconds={segment.start} onSeek={onSeek} />
        <span style={{ fontFamily: tokens.fontFamilyMono, fontSize: tokens.fontMicro, color: tokens.textTertiary, flexShrink: 0 }}>
          -{formatClock(segment.end)}
        </span>
        <SourceBadge source={segment.source} />
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
    <div style={{ display: 'flex', gap: tokens.spaceSm }}>
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
        fontSize: tokens.fontMicro,
        cursor: 'pointer',
        padding: 0,
        flexShrink: 0,
      }}
    >
      {text}
    </button>
  );
}

function SourceBadge({ source }: { source: string | undefined }): React.ReactElement | null {
  if (source === 'ocr_fixed') {
    return <Chip text="OCR 校对" color={tokens.colorSuccess} />;
  }
  if (source === 'review') {
    return <Chip text="待复核" color={tokens.colorWarning} />;
  }
  return null;
}

function Chip({ text, color }: { text: string; color: string }): React.ReactElement {
  return (
    <span
      style={{
        flexShrink: 0,
        fontSize: tokens.fontMicro,
        lineHeight: '14px',
        padding: '0 6px',
        borderRadius: tokens.radiusChip,
        border: `1px solid ${color}`,
        color,
      }}
    >
      {text}
    </span>
  );
}
