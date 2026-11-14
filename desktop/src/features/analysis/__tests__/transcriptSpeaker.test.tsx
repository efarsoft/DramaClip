// @vitest-environment jsdom
/**
 * 转写卡说话人显示（v0.2.5 2.1）：分离链在库而界面零渲染——带 speaker 的段行前缀
 * 出「角色X」Chip；无标签不占位；同一角色恒定同色（看得出谁在说）。
 */
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { AsrSegment } from '@dramaclip/protocol';
import { TranscriptCard } from '../TranscriptCard';

afterEach(cleanup);

function renderCard(segments: AsrSegment[]) {
  render(
    <TranscriptCard
      segments={segments}
      resyncing={false}
      onSeek={vi.fn()}
      onSaveEdit={vi.fn()}
      onResync={vi.fn()}
    />,
  );
}

function chipOf(text: string): HTMLElement {
  const chips = screen.getAllByText(text);
  expect(chips.length).toBeGreaterThan(0);
  expect(chips[0]?.tagName).toBe('SPAN');
  return chips[0] as HTMLElement;
}

it('带 speaker 的段行前缀出角色 Chip', () => {
  renderCard([{ start: 0, end: 2, text: '原句', speaker: '角色A' }]);
  expect(screen.getByText('角色A')).toBeTruthy();
});

it('无 speaker 不占位（纯 ASR/塌缩降级后的行保持原样）', () => {
  renderCard([{ start: 0, end: 2, text: '原句' }]);
  expect(screen.queryByText('角色A')).toBeNull();
});

it('同一角色恒定同色，不同角色颜色不同', () => {
  renderCard([
    { start: 0, end: 2, text: '甲说', speaker: '角色A' },
    { start: 2, end: 4, text: '甲再说', speaker: '角色A' },
    { start: 4, end: 6, text: '乙说', speaker: '角色B' },
  ]);
  const first = chipOf('角色A');
  const repeat = chipOf('角色A');
  const other = chipOf('角色B');
  expect(first.style.color).toBe(repeat.style.color);
  expect(first.style.color).not.toBe(other.style.color);
});
