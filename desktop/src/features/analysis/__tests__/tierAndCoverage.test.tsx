// @vitest-environment jsdom
/**
 * 转写档位三选与金色覆盖度告警的落点（09-10 §4.3② / 静默清单第 1 条）。
 * 粗档灰掉写明原因；告警只在「预筛拦下了一部分集」时出现，数字照实。
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import type { AnalysisResults } from '@dramaclip/protocol';
import { TierPicker } from '../TierPicker';
import { CoverageAlert } from '../WorkbenchPage';

// WorkbenchPage 的模块图会拉起整个数据层；这里只渲染 CoverageAlert，client 全部替身
vi.mock('../../../services/client', () => ({
  rpc: vi.fn(),
  mediaUrl: (path: string): string => path,
  analysisApi: {},
  jobsApi: {},
  projectApi: {},
  exportApi: {},
  narrationApi: {},
  settingsApi: {},
  subtitleApi: {},
}));

beforeAll(() => {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }));
  class NoResizeObserver {
    observe(): void {
      // 浮层尺寸由真浏览器观察
    }

    unobserve(): void {
      // 同上
    }

    disconnect(): void {
      // 同上
    }
  }
  globalThis.ResizeObserver = NoResizeObserver;
});

afterEach(cleanup);

it('档位三选齐备：粗档灰掉，前两档可选', () => {
  render(<TierPicker tier="all" onTierChange={vi.fn()} disabled={false} />);
  expect(screen.getByText('全部精转（默认推荐）')).toBeTruthy();
  expect(screen.getByText('仅推荐集精转')).toBeTruthy();
  const coarse = screen.getByText('未精转集走粗档');
  expect(coarse).toBeTruthy();
  const radios = screen.getAllByRole('radio');
  expect(radios).toHaveLength(3);
  expect(radios[2]?.hasAttribute('disabled')).toBe(true);
  expect(radios[0]?.hasAttribute('disabled')).toBe(false);
});

it('点「仅推荐集精转」上报 recommended；分析中整组禁用', () => {
  const onTierChange = vi.fn();
  render(<TierPicker tier="all" onTierChange={onTierChange} disabled={false} />);
  const radios = screen.getAllByRole('radio');
  const recommended = radios[1];
  if (recommended === undefined) throw new Error('第二档不存在');
  fireEvent.click(recommended);
  expect(onTierChange).toHaveBeenCalledWith('recommended');

  cleanup();
  render(<TierPicker tier="all" onTierChange={vi.fn()} disabled />);
  for (const radio of screen.getAllByRole('radio')) {
    expect(radio.hasAttribute('disabled')).toBe(true);
  }
});

it('覆盖度告警：预筛拦下 1 集时金色说出口，数字照实', () => {
  const results: AnalysisResults = {
    episodes: [
      { episode_id: 'a', episode_number: 1, status: 'done', asr_segment_count: 3, scene_count: 1, highlight_count: 1, recommended: true },
      { episode_id: 'b', episode_number: 2, status: 'done', asr_segment_count: 2, scene_count: 1, highlight_count: 0, recommended: true },
      { episode_id: 'c', episode_number: 3, status: 'prescreened', asr_segment_count: 0, scene_count: 0, highlight_count: 0, recommended: false },
    ],
  };
  const { container } = render(<CoverageAlert results={results} />);
  expect(container.textContent).toContain('预筛只放行 2/3 集进入精转');
  expect(container.textContent).toContain('其余 1 集的台词没有进入模型视野');
});

it('没预筛过 / 全部放行：不出告警——不拿没发生的事吓人', () => {
  const none: AnalysisResults = {
    episodes: [
      { episode_id: 'a', episode_number: 1, status: 'done', asr_segment_count: 3, scene_count: 1, highlight_count: 1, recommended: null },
    ],
  };
  expect(render(<CoverageAlert results={none} />).container.textContent).toBe('');
  const all: AnalysisResults = {
    episodes: [
      { episode_id: 'a', episode_number: 1, status: 'done', asr_segment_count: 3, scene_count: 1, highlight_count: 1, recommended: true },
    ],
  };
  expect(render(<CoverageAlert results={all} />).container.textContent).toBe('');
  expect(render(<CoverageAlert results={null} />).container.textContent).toBe('');
});
