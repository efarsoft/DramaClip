// @vitest-environment node
/**
 * 设置页分区 spec（09-10 §4.6 / 卷二 #9）：两分区补入 + 键与消费端同源验收。
 * KNOWN_KEYS 是 service config.DEFAULTS 的镜像——服务端加键不会红，
 * 界面摆出服务端不认识的键才会红（假控件的第一道闸）。
 */
import { describe, expect, it } from 'vitest';
import { buildSections, type DynamicOptions } from '../sections';

/** service/dramaclip/infra/config.py DEFAULTS 的现有键（镜像，随服务端演进对账）。 */
const KNOWN_KEYS = new Set([
  'analysis.prescreen_threshold',
  'analysis.full_threshold',
  'narration.variants_per_mode',
  'narration.style_id',
  'subtitle.default_preset',
  'subtitle.smart_match',
  'export.loudness_target_lufs',
  'export.loudness_true_peak_dbtp',
  'export.encoder',
  'export.width',
  'export.height',
  'download.hf_mirror',
  'download.ms_base',
  'hardware.max_parallel_jobs',
]);

const dynamic: DynamicOptions = {
  styles: [{ label: '通用', value: 'general' }],
  presets: [{ label: '冲突冲击', value: 'conflict-impact' }],
};

function section(id: string) {
  for (const candidate of buildSections(dynamic)) {
    if (candidate.id === id) return candidate;
  }
  throw new Error(`分区不存在：${id}`);
}

describe('两分区补入', () => {
  it('「生产线默认值」有 K 默认 / 风格默认 / 时长档（从出片区搬来）', () => {
    const keys = section('production').fields.map((field) => field.key);
    expect(keys).toEqual([
      'narration.variants_per_mode',
      'narration.style_id',
    ]);
    expect(section('production').title).toBe('生产线默认值');
  });

  it('「字幕」分区接回 default_preset（有真消费端：export 渲染烧录）', () => {
    const fields = section('subtitle').fields;
    expect(fields.map((field) => field.key)).toEqual(['subtitle.default_preset']);
    expect(fields[0]?.options?.({})).toEqual(dynamic.presets);
  });

  it('subtitle.smart_match 无消费端：不摆假控件', () => {
    const allKeys = buildSections(dynamic).flatMap((s) => s.fields.map((f) => f.key));
    expect(allKeys).not.toContain('subtitle.smart_match');
  });

  it('风格默认选项：「自动匹配」置顶，目录来自注入（与出片中心同键同源）', () => {
    const styleField = section('production').fields.find((f) => f.key === 'narration.style_id');
    expect(styleField?.options?.({})).toEqual([
      { label: '自动匹配（推荐）', value: 'auto' },
      { label: '通用', value: 'general' },
    ]);
  });
});

describe('键与消费端同源验收', () => {
  it('界面上每个控件的键都是服务端认识的键', () => {
    const allKeys = buildSections(dynamic).flatMap((s) => s.fields.map((f) => f.key));
    for (const key of allKeys) {
      expect(KNOWN_KEYS.has(key), key).toBe(true);
    }
  });

  it('分区顺序：出片 → 生产线默认值 → 分析 → 字幕 → 下载 → 硬件', () => {
    expect(buildSections(dynamic).map((s) => s.id)).toEqual([
      'export',
      'production',
      'analysis',
      'subtitle',
      'download',
      'hardware',
    ]);
  });
});
