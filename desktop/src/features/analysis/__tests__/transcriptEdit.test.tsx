// @vitest-environment jsdom
/**
 * 转写行内编辑提交规则（09-10 §4.3②「修失焦静默丢弃」）：
 * 回车提交、Esc 显式取消、失焦提交非空改动；删段仍是显式动作（清空回车），失焦不误删。
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { AsrSegment } from '@dramaclip/protocol';
import { TranscriptCard } from '../TranscriptCard';

const SEGMENTS: AsrSegment[] = [{ start: 0, end: 2, text: '原句' }];

afterEach(cleanup);

function card(onSaveEdit = vi.fn()) {
  render(
    <TranscriptCard
      segments={SEGMENTS}
      resyncing={false}
      onSeek={vi.fn()}
      onSaveEdit={onSaveEdit}
      onResync={vi.fn()}
    />,
  );
  return onSaveEdit;
}

function openEditor(): HTMLElement {
  fireEvent.click(screen.getByText('原句'));
  const input = screen.getByRole('textbox');
  return input;
}

it('失焦提交非空改动——不再静默丢弃', () => {
  const onSaveEdit = card();
  const input = openEditor();
  fireEvent.change(input, { target: { value: '改后的句子' } });
  fireEvent.blur(input);
  expect(onSaveEdit).toHaveBeenCalledWith(0, '改后的句子');
});

it('失焦时没改动：不发保存', () => {
  const onSaveEdit = card();
  const input = openEditor();
  fireEvent.blur(input);
  expect(onSaveEdit).not.toHaveBeenCalled();
});

it('清空后失焦：视为放弃编辑，不误删段', () => {
  const onSaveEdit = card();
  const input = openEditor();
  fireEvent.change(input, { target: { value: '' } });
  fireEvent.blur(input);
  expect(onSaveEdit).not.toHaveBeenCalled();
});

it('清空回车：显式删除该段（原有规则保留）', () => {
  const onSaveEdit = card();
  const input = openEditor();
  fireEvent.change(input, { target: { value: '' } });
  fireEvent.keyDown(input, { key: 'Enter' });
  expect(onSaveEdit).toHaveBeenCalledWith(0, '');
});

it('回车提交；Esc 显式取消不发保存', () => {
  const onSaveEdit = card();
  const input = openEditor();
  fireEvent.change(input, { target: { value: '回车句' } });
  fireEvent.keyDown(input, { key: 'Enter' });
  expect(onSaveEdit).toHaveBeenCalledWith(0, '回车句');

  const second = openEditor();
  fireEvent.change(second, { target: { value: '不要了' } });
  fireEvent.keyDown(second, { key: 'Escape' });
  expect(onSaveEdit).toHaveBeenCalledTimes(1);
});
