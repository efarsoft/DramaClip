/** modeMeta：九种可供应模式的展示信息 + 退役模式的展示名（只在旧方案里出现）。 */
import { describe, expect, it } from 'vitest';
import { MODE_INFO, modeLabel } from '../modeMeta';

describe('modeLabel', () => {
  it('九种可供应模式都有中文名（模式九宫格的可选面就是这张表）', () => {
    expect(MODE_INFO).toHaveLength(9);
    expect(MODE_INFO.every((item) => item.label !== '' && item.desc !== '')).toBe(true);
    expect(modeLabel('dialogue_narration')).toBe('剧情解说');
  });

  it('已完全移除的模式不在可选面，原样显示 id（高光混剪 2026-11-12 清除）', () => {
    expect(MODE_INFO.some((item) => item.mode === 'highlight_cut')).toBe(false);
    expect(modeLabel('highlight_cut')).toBe('highlight_cut');
  });

  it('未知模式原样显示、没有模式统称成片（宁可露 id 不给空白）', () => {
    expect(modeLabel('mystery_mode')).toBe('mystery_mode');
    expect(modeLabel(undefined)).toBe('成片');
  });
});
