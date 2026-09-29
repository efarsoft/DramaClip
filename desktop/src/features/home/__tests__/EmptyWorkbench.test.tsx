/** 无剧时的主区引导（规格 §4.1 空态 + §4.2 首启三步）。它必须给出唯一那个 primary，
 *  因为有剧时 primary 在 PageHeader 上、空态时不在——两处都放会违反
 *  DSS §3.1「每屏 primary 至多 1 个」。三步引导自身的勾选逻辑在 OnboardingSteps。 */
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { EmptyWorkbench } from '../EmptyWorkbench';

afterEach(cleanup);

function renderEmpty(models: Parameters<typeof EmptyWorkbench>[0]['models'] = null, llmBaseUrl = '') {
  const onCreate = vi.fn();
  const view = render(
    <MemoryRouter>
      <EmptyWorkbench creating={false} onCreate={onCreate} models={models} llmBaseUrl={llmBaseUrl} />
    </MemoryRouter>,
  );
  return { ...view, onCreate };
}

describe('EmptyWorkbench', () => {
  it('一句话说清开始形态（三步引导 + 素材已在本地）', () => {
    renderEmpty();
    expect(screen.getByText(/三步开始/)).toBeTruthy();
    expect(screen.getByText('装一个 ASR 模型')).toBeTruthy();
  });

  it('primary 仍只有一个（新增项目）；三步的直达入口是普通按钮不算 primary', () => {
    const { onCreate } = renderEmpty();
    const primaries = document.querySelectorAll<HTMLElement>('.ant-btn-primary');
    expect(primaries).toHaveLength(1);
    expect(primaries[0]?.textContent).toContain('新增项目');
    primaries[0]?.click();
    expect(onCreate).toHaveBeenCalledTimes(1);
  });

  it('建剧中时按钮进 loading 且不可再点', () => {
    render(
      <MemoryRouter>
        <EmptyWorkbench creating onCreate={vi.fn()} models={null} llmBaseUrl="" />
      </MemoryRouter>,
    );
    // 「新增项目」有两个命中（三步引导的步名 + primary 按钮）：primary 只有一个
    const primary = document.querySelector<HTMLElement>('.ant-btn-primary');
    expect(primary?.textContent).toContain('新增项目');
    expect(primary?.hasAttribute('disabled')).toBe(true);
  });

  it('不承诺任何未实装的能力（无拖放、无下载短剧、无网盘）', () => {
    const { container } = renderEmpty();
    const text = container.textContent;
    for (const banned of ['拖', '下载短剧', '网盘', '授权书', '即将']) {
      expect(text, `空态文案里出现了 ${banned}`).not.toContain(banned);
    }
  });
});
