import type { AsrSegment, PlanData } from '@dramaclip/protocol';

export interface CopyRow {
  readonly kind: 'original' | 'narration';
  readonly episodeNumber: number | null;
  readonly start: number;
  readonly end: number;
  readonly text: string;
}

/**
 * 时间轴 + 槽位文案 + ASR 台词 → 原声/旁白交替清单（完整文案结构化展示）。
 *
 * 旁白段与 narration_texts 按出现顺序一一配对（编排层同一循环成对追加，剧本清洗
 * 层丢段时两侧同步缺）；原声段取窗口相交的 ASR 台词行，无分析数据时退化为纯旁白
 * （与旧行为一致）。
 */
export function copyRowsOf(
  plan: PlanData,
  episodes: readonly { episode_id: string; episode_number: number }[],
  asrSegments?: Readonly<Record<string, AsrSegment[]>>,
): CopyRow[] {
  const numberById = new Map(episodes.map((e) => [e.episode_id, e.episode_number]));
  const rows: CopyRow[] = [];
  let slotIndex = 0;
  for (const segment of plan.timeline) {
    const episodeNumber = numberById.get(segment.episode_id) ?? null;
    if (segment.audio === 'narration' || segment.audio === 'ducked') {
      const item = plan.narration_texts[slotIndex];
      slotIndex += 1;
      if (item?.text) {
        rows.push({ kind: 'narration', episodeNumber, start: segment.start, end: segment.end, text: item.text });
      }
      continue;
    }
    const inside = (asrSegments?.[segment.episode_id] ?? []).filter(
      (line: AsrSegment) => line.start < segment.end && line.end > segment.start,
    );
    const text =
      inside.map((line) => line.text.trim()).join(' / ') ||
      (segment.subtitle_text ?? '').trim() ||
      '（无台词转写）';
    rows.push({ kind: 'original', episodeNumber, start: segment.start, end: segment.end, text });
  }
  return rows;
}


