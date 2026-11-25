// @vitest-environment node
/** worksView 纯逻辑：徽章三态文案与度量原文、绝对时间、取材区间、分组合计。 */
import { describe, expect, it } from 'vitest';
import type { Episode, SelfCheck, WorkItem } from '@dramaclip/protocol';
import {
  episodeLabel,
  formatDate,
  formatTotalGb,
  formatWhen,
  groupWorks,
  selectedBytes,
  selfCheckBadges,
  selfCheckReadings,
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

  it('筛选词表：全部/自检通过/有红/有灰/未检（有灰无红=partial，规格 §1.4）', () => {
    expect(WORKS_FILTERS.map((f) => f.label)).toEqual(['全部', '自检通过', '有红', '有灰', '未检']);
  });
});

describe('自检读数行（四项徽章之外）', () => {
  it('早期成绩单没有这些键：一行都不编', () => {
    expect(selfCheckReadings(selfcheck())).toEqual([]);
    expect(selfCheckReadings(null)).toEqual([]);
  });

  it('响度读数上屏：不设徽章（导出门禁已守门），只列复核实测', () => {
    const [row] = selfCheckReadings({
      ...selfcheck(),
      loudness: {
        status: 'measured',
        measured_i: -14.6,
        measured_tp: -1.2,
        lra: 8.4,
        target_i: -14,
        target_tp: -1.5,
        deviation_lu: 0.6,
      },
    });
    expect(row).toMatchObject({ key: 'loudness', tone: 'none', text: '响度读数' });
    expect(row?.detail).toContain('综合响度 -14.6 LUFS（目标 -14.0，偏 0.6 LU）');
    expect(row?.detail).toContain('真峰值 -1.2 dBTP（上限 -1.5）');
    expect(row?.detail).toContain('响度范围 8.4 LU');
  });

  it('开场质检三态；原声模式（null）不出行', () => {
    const red = selfCheckReadings({
      ...selfcheck(),
      opening: { pass: false, window_s: 3, mean_volume_db: -61, reason: '开场静默黑洞：前 3s mean -61.0 dB' },
    });
    expect(red[0]).toMatchObject({
      key: 'opening',
      tone: 'fail',
      text: '✕ 开场静默',
      detail: '开场静默黑洞：前 3s mean -61.0 dB',
    });
    expect(selfCheckReadings({ ...selfcheck(), opening: null })).toEqual([]);
  });

  it('收尾出点：服务端的原因码翻成人话，带上时间点与被切断的那句', () => {
    const [row] = selfCheckReadings({
      ...selfcheck(),
      ending: { pass: false, reason: 'mid_line', end_s: 134.25, line: '你到底想干什么' },
    });
    expect(row).toMatchObject({ key: 'ending', tone: 'fail', text: '✕ 收尾把话切断' });
    expect(row?.detail).toBe('最后一刀在 134.3s，落在台词「你到底想干什么」中间——话被拦腰');
  });

  it('音画同步：样本不足如实说量不到，不发绿勾', () => {
    const grey = selfCheckReadings({ ...selfcheck(), avsync: { pass: null } });
    expect(grey[0]).toMatchObject({
      key: 'avsync',
      tone: 'none',
      text: '— 音画同步未检',
      detail: '有效采样点不足两点，量不到',
    });
    const ok = selfCheckReadings({
      ...selfcheck(),
      avsync: { pass: true, median_ms: 12.3, dispersion_ms: 20, samples: 3 },
    });
    expect(ok[0]).toMatchObject({ tone: 'ok', text: '✓ 音画同步' });
    expect(ok[0]?.detail).toBe('各采样点偏移中位 12.3 ms · 离散 20.0 ms · 3 点 · 判据均 ≤ 40 ms');
  });

  it('画面落位带三态；残字影子只报计数、不作判定', () => {
    const rows = selfCheckReadings({
      ...selfcheck(),
      caption_placement: {
        pass: true,
        measured_top: 0.8,
        measured_bottom: 0.9,
        expected_top: 0.79,
        expected_bottom: 0.91,
        center_offset: 0.01,
        cover_tolerance: 0.08,
      },
      caption_residue: { pass: null, band_frames: 10, residue_frames: 2, samples: [] },
    });
    expect(rows[0]).toMatchObject({ key: 'caption_placement', tone: 'ok', text: '✓ 字幕盖住台词带' });
    expect(rows[0]?.detail).toContain('字幕实测 0.80–0.90 · 台词带 0.79–0.91');
    expect(rows[1]).toMatchObject({
      key: 'caption_residue',
      tone: 'none',
      detail: '字幕带内多出一簇文字的帧 2/10（攒数据用，不作判定）',
    });
  });

  it('残字影子没采样到带内文字：不出行', () => {
    expect(
      selfCheckReadings({
        ...selfcheck(),
        caption_residue: { pass: null, reason: '未采样或无覆盖承诺', band_frames: 0, residue_frames: 0, samples: [] },
      }),
    ).toEqual([]);
  });
});

describe('时间与体积', () => {
  it('完成时间是绝对 M/D HH:mm，不是「昨天」话术', () => {
    const label = formatWhen(new Date(2026, 8, 23, 9, 5).getTime());
    expect(label).toBe('9/23 09:05');
    expect(formatWhen(undefined)).toBe('');
  });

  it('日期是绝对 YYYY/MM/DD（只到日）；缺失报「—」——与 formatWhen 语义不同', () => {
    expect(formatDate(new Date(2026, 8, 23, 9, 5).getTime())).toBe('2026/09/23');
    expect(formatDate(undefined)).toBe('—');
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
