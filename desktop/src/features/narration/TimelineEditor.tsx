import { Button, Card, InputNumber } from 'antd';
import { useState } from 'react';
import type { NarrationPlan, TimelineSegment } from '@dramaclip/protocol';
import { rpc } from '../../services/client';
import { tokens } from '../../styles/theme';

interface EditorProps {
  plan: NarrationPlan;
  onChanged: () => void;
}

/** 时间线编辑器（W13 简化版）：段选中 → 起止微调/删除 → 整轴保存（拖拽画布 P2）。 */
export function TimelineEditor({ plan, onChanged }: EditorProps) {
  const [index, setIndex] = useState<number | null>(null);
  const [segments, setSegments] = useState<TimelineSegment[] | null>(null);
  const [saving, setSaving] = useState(false);

  const current: TimelineSegment[] = segments ?? [...plan.plan_data.timeline];

  const update = (patch: Partial<TimelineSegment>): void => {
    if (index === null) return;
    setSegments(current.map((seg, i) => (i === index ? { ...seg, ...patch } : seg)));
  };

  const remove = (i: number): void => {
    setSegments(current.filter((_, iter) => iter !== i));
    setIndex(null);
  };

  const save = async (): Promise<void> => {
    if (segments === null) return;
    setSaving(true);
    try {
      await rpc('narration.replace_timeline', { plan_id: plan.id, segments });
      onChanged();
    } finally {
      setSaving(false);
    }
  };

  const dirty = segments !== null;

  return (
    <Card
      size="small"
      type="inner"
      title="时间线编辑"
      extra={
        dirty ? (
          <EditActions
            onRevert={() => { setSegments(null); }}
            saving={saving}
            onSave={() => { void save(); }}
          />
        ) : undefined
      }
    >
      {current.length === 0 ? (
        <div style={{ color: tokens.textTertiary, fontSize: tokens.fontCaption }}>无段</div>
      ) : (
        <SegmentRows
          segments={current}
          selectedIndex={index}
          onSelect={setIndex}
          onPatch={update}
          onRemove={remove}
        />
      )}
    </Card>
  );
}

function EditActions({
  onRevert,
  saving,
  onSave,
}: {
  onRevert: () => void;
  saving: boolean;
  onSave: () => void;
}) {
  return (
    <div style={{ display: 'flex', gap: 8 }}>
      <Button size="small" onClick={onRevert}>
        还原
      </Button>
      <Button size="small" type="primary" loading={saving} onClick={onSave}>
        保存
      </Button>
    </div>
  );
}

function SegmentRows({
  segments,
  selectedIndex,
  onSelect,
  onPatch,
  onRemove,
}: {
  segments: TimelineSegment[];
  selectedIndex: number | null;
  onSelect: (index: number) => void;
  onPatch: (patch: Partial<TimelineSegment>) => void;
  onRemove: (index: number) => void;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {segments.map((segment, i) => (
        <SegmentEditRow
          key={`${String(segment.start)}-${String(i)}`}
          index={i}
          segment={segment}
          selected={selectedIndex === i}
          onSelect={onSelect}
          onPatch={onPatch}
          onRemove={onRemove}
        />
      ))}
    </div>
  );
}

function SegmentEditRow({
  index,
  segment,
  selected,
  onSelect,
  onPatch,
  onRemove,
}: {
  index: number;
  segment: TimelineSegment;
  selected: boolean;
  onSelect: (index: number) => void;
  onPatch: (patch: Partial<TimelineSegment>) => void;
  onRemove: (index: number) => void;
}) {
  const bg = selected ? 'rgba(77,159,255,0.08)' : 'transparent';
  const border = selected ? tokens.colorPrimary : 'transparent';
  return (
    <div
      onClick={() => { onSelect(index); }}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '4px 8px',
        borderRadius: tokens.radiusThumb,
        cursor: 'pointer',
        background: bg,
        border: `1px solid ${border}`,
        fontSize: tokens.fontBody,
      }}
    >
      <span style={{ color: tokens.textTertiary, width: 24, fontFamily: tokens.fontFamilyMono }}>
        {String(index + 1)}
      </span>
      <NumberInput
        value={segment.start}
        step={0.5}
        onChange={(v) => { onPatch({ start: v }); }}
      />
      <span style={{ color: tokens.textTertiary }}>→</span>
      <NumberInput
        value={segment.end}
        step={0.5}
        onChange={(v) => { onPatch({ end: v }); }}
      />
      <span style={{ fontSize: tokens.fontMicro, color: audioColor(segment.audio) }}>{audioLabel(segment.audio)}</span>
      {segment.subtitle_text !== null && segment.subtitle_text !== undefined && (
        <span style={{ fontSize: tokens.fontMicro, color: tokens.textSecondary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 200 }}>
          {segment.subtitle_text}
        </span>
      )}
      <Button size="small" danger type="text" style={{ marginLeft: 'auto' }} onClick={() => { onRemove(index); }}>
        删除
      </Button>
    </div>
  );
}

function NumberInput({
  value,
  step,
  onChange,
}: {
  value: number;
  step: number;
  onChange: (v: number) => void;
}) {
  return (
    <InputNumber
      size="small"
      value={value}
      step={step}
      min={0}
      controls={false}
      style={{ width: 76, fontFamily: tokens.fontFamilyMono }}
      onClick={(e) => { e.stopPropagation(); }}
      onChange={(v) => {
        if (typeof v === 'number') onChange(v);
      }}
    />
  );
}

function audioLabel(audio: string): string {
  return { original: '原声', narration: '旁白', ducked: '压低' }[audio] ?? audio;
}

function audioColor(audio: string): string {
  return { original: '#60A5FA', narration: '#FBBF24', ducked: '#9CA3AF' }[audio] ?? tokens.textTertiary;
}
