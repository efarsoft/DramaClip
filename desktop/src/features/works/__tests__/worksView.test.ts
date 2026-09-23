// @vitest-environment node
/** worksView 纯逻辑：徽章三态文案与度量原文、绝对时间、取材区间、分组合计。 */
import { describe, expect, it } from 'vitest';
import type { Episode, SelfCheck, WorkItem } from '@dramaclip/protocol';
import {
  episodeLabel,
  formatTotalGb,
  formatWhen,
  groupWorks,
  selectedBytes,
  selfCheckBadges,
  WORKS_FILTERS,
} from '../worksView';

function work(over: Partial<WorkItem> = {}): WorkItem {
  return {
    id: 'w1',
    project_id: 'p1',
    project_name: '甲剧',
    narration_mode: 'full_narration',
    output_path: 'D:/out/a.mp4',
    completed_at: 100,
    ...over,
  };
}

function selfcheck(over: Partial<Record<'duration' | 'narration' | 'silence' | 'freeze', { pass: boolean | null }>> = {}): SelfCheck {
  const base = {
    duration: { pass: true, measured_s: 134, budget_s: 134, tolerance_s: 10.7 },
    narration: { pass: true, has_audio: true, expected: 'many', planned_segments: 8 },
    silence: { pass: true, mean_volume_db: -23.4 },
    freeze: { pass: true, max_freeze_s: 0 },
  };
  // 按项合并：只改 pass 时保留度量字段——服务端真载荷里 fail 项也带着实测值
  return {
    checked_at: 1758600000000,
    duration: { ...base.duration, ...over.duration },
    narration: { ...base.narration, ...over.narration },
    silence: { ...base.silence, ...over.silence },
    freeze: { ...base.freeze, ...over.freeze },
  };
}

describe('自检徽章三态', () => {
  it('从未自检：四项全部灰「—」，绝不发绿勾', () => {
    const badges = selfCheckBadges(null);
    expect(badges).toHaveLength(4);
    for (const badge of badges) {
      expect(badge.tone).toBe('none');
      expect(badge.text.startsWith('—')).toBe(true);
    }
  });

  it('全绿：四项 ✓ 实底', () => {
    const badges = selfCheckBadges(selfcheck());
    expect(badges.map((b) => b.tone)).toEqual(['ok', 'ok', 'ok', 'ok']);
    expect(badges[0]?.text).toBe('✓ 时长达标');
    expect(badges[3]?.text).toBe('✓ 无长冻结帧');
  });

  it('红项带度量原文；灰项说明量不到的原因——三态是三种视觉', () => {
    const badges = selfCheckBadges(
      selfcheck({
        duration: { pass: false },
        silence: { pass: null },
      }),
    );
    const duration = badges[0];
    expect(duration?.tone).toBe('fail');
    expect(duration?.text).toBe('✕ 时长不达标');
    expect(duration?.detail).toContain('实测 134.0s');
    const silence = badges[2];
    expect(silence?.tone).toBe('none');
    expect(silence?.text).toBe('— 静音段未检');
  });

  it('无音轨：静音项如实红并写原因', () => {
    const badges = selfCheckBadges(
      selfcheck({ silence: { pass: false, reason: '无音轨' } as { pass: boolean | null } }),
    );
    expect(badges[2]?.detail).toContain('无音轨');
  });

  it('筛选词表：全部/自检通过/有红/未检', () => {
    expect(WORKS_FILTERS.map((f) => f.label)).toEqual(['全部', '自检通过', '有红', '未检']);
  });
});

describe('时间与体积', () => {
  it('完成时间是绝对 M/D HH:mm，不是「昨天」话术', () => {
    const label = formatWhen(new Date(2026, 8, 23, 9, 5).getTime());
    expect(label).toBe('9/23 09:05');
    expect(formatWhen(undefined)).toBe('');
  });

  it('合计体积 GB 两位小数（量化确认的数据源）', () => {
    expect(formatTotalGb(536870912)).toBe('0.50 GB');
    expect(selectedBytes([work({ size_bytes: 100 }), work({ id: 'w2', size_bytes: 200 })])).toBe(300);
    expect(selectedBytes([work({ size_bytes: undefined })])).toBe(0);
  });
});

describe('取材集标签', () => {
  const episodes = [
    { id: 'e1', episode_number: 4 },
    { id: 'e2', episode_number: 11 },
  ] as Episode[];

  it('集数映射齐全时给区间 EP04–EP11', () => {
    expect(episodeLabel(['e1', 'e2'], episodes)).toBe('取材 EP04–EP11');
    expect(episodeLabel(['e1'], episodes)).toBe('取材 EP04');
  });

  it('映射不齐只报条数；缺失给空串——拿不到的不编', () => {
    expect(episodeLabel(['e1', 'x9'], episodes)).toBe('取材 2 集');
    expect(episodeLabel(['e1', 'e2'])).toBe('取材 2 集');
    expect(episodeLabel(null)).toBe('');
    expect(episodeLabel([])).toBe('');
  });
});

describe('分组', () => {
  it('按剧分组，剧内与剧间都按完成时间倒序', () => {
    const groups = groupWorks([
      work({ id: 'a', project_id: 'p1', project_name: '甲', completed_at: 10 }),
      work({ id: 'b', project_id: 'p2', project_name: '乙', completed_at: 30 }),
      work({ id: 'c', project_id: 'p1', project_name: '甲', completed_at: 20 }),
    ]);
    expect(groups.map((g) => g.name)).toEqual(['乙', '甲']);
    expect(groups[1]?.works.map((w) => w.id)).toEqual(['c', 'a']);
  });
});
