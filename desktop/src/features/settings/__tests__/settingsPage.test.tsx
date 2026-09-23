// @vitest-environment jsdom
/**
 * 设置页两分区接线（P-C⑨）：目录类选项异步注入，取不到就空目录——
 * 控件照实显示当前值，不编选项、不假绿。
 */
import { App as AntdApp } from 'antd';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { SettingsPage } from '../SettingsPage';

const api = vi.hoisted(() => ({
  get: vi.fn(),
  listStyles: vi.fn(),
  listPresets: vi.fn(),
}));

vi.mock('../../../services/client', () => ({
  rpc: (method: string): unknown => (method === 'settings.get' ? api.get() : Promise.reject(new Error(`未预期方法 ${method}`))),
  narrationApi: { listStyles: (): unknown => api.listStyles() },
  subtitleApi: { listPresets: (): unknown => api.listPresets() },
}));

const VALUES: Record<string, string> = {
  'narration.variants_per_mode': '3',
  'narration.style_id': 'auto',
  'subtitle.default_preset': 'conflict-impact',
  'strategy.min_duration_s': '30',
  'strategy.max_duration_s': '300',
};

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

function page() {
  return render(
    <AntdApp>
      <SettingsPage />
    </AntdApp>,
  );
}

afterEach(() => {
  cleanup();
  api.get.mockReset();
  api.listStyles.mockReset();
  api.listPresets.mockReset();
});

it('六分区齐备；字幕预设与风格目录取回后按名字显示', async () => {
  api.get.mockResolvedValue(VALUES);
  api.listStyles.mockResolvedValue([{ style_id: 'general', name: '通用', directives: '' }]);
  api.listPresets.mockResolvedValue([
    { preset_id: 'conflict-impact', preset_name: '冲突冲击', description: '' },
  ]);
  page();

  for (const title of ['出片', '生产线默认值', '智能分析', '字幕', '下载加速', '硬件']) {
    expect(await screen.findByText(title)).toBeTruthy();
  }
  expect(screen.getByText('每个模式出几条方案 (K)')).toBeTruthy();
  expect(screen.getByText('内封字幕默认预设')).toBeTruthy();
  // 目录注入后：select 显示的是人读名字，不是裸 id
  expect(await screen.findByText('冲突冲击')).toBeTruthy();
  expect(await screen.findByText('自动匹配（推荐）')).toBeTruthy();
});

it('预设目录取不到：不崩、不编选项，照实显示当前值原文', async () => {
  api.get.mockResolvedValue(VALUES);
  api.listStyles.mockRejectedValue(new Error('管道断开'));
  api.listPresets.mockRejectedValue(new Error('管道断开'));
  page();

  expect(await screen.findByText('内封字幕默认预设')).toBeTruthy();
  // 没有匹配选项时 antd Select 直接呈现值本身——这就是「照实」
  expect(await screen.findByText('conflict-impact')).toBeTruthy();
  // 风格字段的「自动匹配」是 spec 内置项，目录挂了它也在——显示的是人读名而非裸 auto
  expect(await screen.findByText('自动匹配（推荐）')).toBeTruthy();
});
