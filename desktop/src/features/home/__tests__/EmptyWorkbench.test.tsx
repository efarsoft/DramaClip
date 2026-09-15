/** 无剧时的主区引导（规格 §4.1 空态）。它必须给出唯一那个 primary，
 *  因为有剧时 primary 在 PageHeader 上、空态时不在——两处都放会违反
 *  DSS §3.1「每屏 primary 至多 1 个」。 */
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { EmptyWorkbench } from '../EmptyWorkbench';

afterEach(cleanup);

function renderEmpty() {
  const onCreate = vi.fn();
  const view = render(
    <MemoryRouter>
      <EmptyWorkbench creating={false} onCreate={onCreate} />
    </MemoryRouter>,
  );
  return { ...view, onCreate };
}

describe('EmptyWorkbench', () => {
  it('一句话说清产品从哪开始（素材已在本地，不做下载）', () => {
    renderEmpty();
    expect(screen.getByText(/素材已在本地/)).toBeTruthy();
  });

  it('给出唯一的主按钮，点下去触发建剧', () => {
    const { onCreate } = renderEmpty();
    const buttons = screen.queryAllByRole('button');
    expect(buttons).toHaveLength(1);
    expect(buttons[0]?.textContent).toContain('新增项目');
    buttons[0]?.click();
    expect(onCreate).toHaveBeenCalledTimes(1);
  });

  it('建剧中时按钮进 loading 且不可再点', () => {
    render(
      <MemoryRouter>
        <EmptyWorkbench creating onCreate={vi.fn()} />
      </MemoryRouter>,
    );
    const button = screen.getByRole('button');
    expect(button.hasAttribute('disabled')).toBe(true);
  });

  it('不承诺任何未实装的能力（无拖放、无下载、无网盘）', () => {
    const { container } = renderEmpty();
    const text = container.textContent;
    for (const banned of ['拖', '下载短剧', '网盘', '授权书', '即将']) {
      expect(text, `空态文案里出现了 ${banned}`).not.toContain(banned);
    }
  });
});
