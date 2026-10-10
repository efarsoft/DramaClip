/** 转写卡片：分段文本可点击定位、行内编辑（回车提交、Esc 取消、失焦提交非空修改；清空回车删段）。 */
import { Button, Card } from 'antd';
import { useState } from 'react';
import type { AsrSegment } from '@dramaclip/protocol';
import { layout, tokens } from '../../styles/theme';

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
      title="ASR 转写（点击文本修正：回车提交、Esc 取消、失焦提交改动；清空回车删除该段）"
      extra={
        <Button size="small" loading={resyncing} onClick={onResync}>
          重跑语义
        </Button>
      }
    >
      {segments.length === 0 ? (
        <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>尚未转写</span>
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
  fontSize: tokens.text.body.size,
  lineHeight: tokens.text.body.leading,
  padding: `${String(layout.inlineInput.paddingBlock)}px ${layout.inlineInput.paddingInline}`,
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
      <div style={{ display: 'flex', gap: tokens.spaceSm, fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, alignItems: 'baseline' }}>
        <SeekButton seconds={segment.start} onSeek={onSeek} />
        <span style={{ fontFamily: tokens.fontFamilyMono, fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary, flexShrink: 0 }}>
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
          if (event.key === 'Escape') {
            // 显式取消：明确表达「不要这次修改」，与失焦的「顺手提交」是两回事
            setEditing(false);
            return;
          }
          if (event.key !== 'Enter') return;
          onSaveEdit(index, draft.trim());
          setEditing(false);
        }}
        onBlur={() => {
          // 失焦提交非空改动（修「失焦静默丢弃」，09-10 §4.3②）；
          // 删段是显式动作（清空回车），失焦不误删——清空后失焦视为放弃这次编辑。
          const next = draft.trim();
          setEditing(false);
          if (next !== '' && next !== segment.text) onSaveEdit(index, next);
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
        fontSize: tokens.text.badge.size,
        lineHeight: tokens.text.badge.leading,
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
    return <Chip text="字幕补字" color={tokens.colorSuccess} />;
  }
  if (source === 'llm_refined') {
    return <Chip text="AI 校对" color={tokens.colorPrimary} />;
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
        fontSize: tokens.text.badge.size,
        lineHeight: tokens.text.badge.leading,
        padding: `${String(layout.badgeChip.paddingBlock)}px ${String(layout.badgeChip.paddingInline)}px`,
        borderRadius: tokens.radiusChip,
        border: `1px solid ${color}`,
        color,
      }}
    >
      {text}
    </span>
  );
}
