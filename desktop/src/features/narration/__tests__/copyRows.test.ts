// 完整文案结构化展示的行装配：原声/旁白按时间轴交替，旁白与槽位文案按出现顺序配对。
import { describe, expect, it } from 'vitest';
import type { PlanData } from '@dramaclip/protocol';
import { copyRowsOf } from '../copyRows';

function plan(over?: Partial<PlanData>): PlanData {
  return {
    mode: 'dialogue_narration',
    timeline: [
      { episode_id: 'ep1', start: 32, end: 40, audio: 'original' },
      { episode_id: 'ep1', start: 40, end: 46, audio: 'narration' },
      { episode_id: 'ep2', start: 95, end: 116, audio: 'original' },
    ],
    narration_texts: [{ id: 'n0', text: '谁也没想到，这场婚礼从钻戒开始就是个局' }],
    ...over,
  };
}

const episodes = [
  { episode_id: 'ep1', episode_number: 6 },
  { episode_id: 'ep2', episode_number: 8 },
];

const asr = {
  ep1: [
    { start: 33, end: 35, text: ' 你小心我跟你离婚 ' },
    { start: 36, end: 39, text: '孩子重新找' },
  ],
  ep2: [{ start: 30, end: 50, text: '后面的车必须清一水的迈凯伦' }],
};

describe('copyRowsOf', () => {
  it('按时间轴交替装配：原声行聚合窗口内台词行，旁白行配对槽位文案', () => {
    const rows = copyRowsOf(plan(), episodes, asr);
    expect(rows.map((r) => r.kind)).toEqual(['original', 'narration', 'original']);
    expect(rows[0]?.text).toBe('你小心我跟你离婚 / 孩子重新找');
    expect(rows[0]?.episodeNumber).toBe(6);
    expect(rows[1]?.text).toBe('谁也没想到，这场婚礼从钻戒开始就是个局');
    expect(rows[1]?.episodeNumber).toBe(6);
  });

  it('无分析数据时退化为纯旁白+占位文案（旧行为）', () => {
    const rows = copyRowsOf(plan(), []);
    expect(rows.map((r) => r.kind)).toEqual(['original', 'narration', 'original']);
    expect(rows[0]?.text).toBe('（无台词转写）');
    expect(rows[2]?.text).toBe('（无台词转写）');
    expect(rows[1]?.text).toContain('钻戒');
  });

  it('原声段兜底用自身字幕（金句流形态），空槽位不产生旁白行', () => {
    const rows = copyRowsOf(
      plan({
        timeline: [
          { episode_id: 'ep1', start: 0, end: 8, audio: 'original', subtitle_text: '你给我滚出去！骗子！' },
        ],
        narration_texts: [{ id: 'n0', text: '' }],
      }),
      episodes,
      undefined,
    );
    expect(rows).toHaveLength(1);
    expect(rows[0]?.kind).toBe('original');
    expect(rows[0]?.text).toBe('你给我滚出去！骗子！');
  });
});
