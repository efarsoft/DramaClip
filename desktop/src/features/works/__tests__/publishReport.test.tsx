// @vitest-environment jsdom
/**
 * 数据报告抽屉（批二#7/#9 界面）：聚合行/信号/离群点名、健康线横幅带校准标注、
 * 加载失败诚实上屏不伪装空表、空账如实提示去录入。
 * mock 手法仿 worksDetail.test.tsx（vi.hoisted + vi.mock client）；
 * 断言用 toBeTruthy()——仓库未装 jest-dom，与 worksDetail/worksPage 同口径。
 */
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { App as AntdApp } from 'antd';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { PublishReport } from '@dramaclip/protocol';
import { PublishReportDrawer } from '../PublishReportDrawer';

const api = vi.hoisted(() => ({ publishReport: vi.fn() }));
vi.mock('../../../services/client', () => ({
  exportApi: { publishReport: api.publishReport },
}));

const REPORT: PublishReport = {
  dimension: 'mode',
  rows: [{
    value: 'full_narration', n: 12, median_retention_pct: 35.5,
    like_rate: 0.04, share_rate: 0.012, signal: 'yellow', outliers: ['e-outlier-1'],
  }],
  recorded: 12, zero_plays_excluded: 1,
  health: {
    line_3s: 32, line_retention: 30, note: '通用基准初始值，回流数据足够后自建校准',
    below: [{
      export_id: 'e1', project_name: '剧一', metric: 'retention_3s',
      value: 20, suggestion: '钩子重选：前3秒留存低于基准，开场钩子没留住人',
    }],
  },
};

function renderDrawer() {
  return render(
    <AntdApp><PublishReportDrawer open onClose={() => undefined} /></AntdApp>,
  );
}

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

beforeEach(() => { vi.clearAllMocks(); });

afterEach(() => { cleanup(); });

describe('PublishReportDrawer', () => {
  it('渲染聚合行、信号与离群点名', async () => {
    api.publishReport.mockResolvedValue(REPORT);
    renderDrawer();
    await waitFor(() => { expect(screen.getByText('full_narration')).toBeTruthy(); });
    expect(screen.getByText('35.5%')).toBeTruthy();
    // 精确串只命中信号 Tag：页脚纪律句「黄标仅趋势参考」也含这四个字，正则会双命中
    expect(screen.getByText('趋势参考')).toBeTruthy();
    expect(screen.getByText(/e-outlie/)).toBeTruthy();
    expect(api.publishReport).toHaveBeenCalledWith('mode');
  });

  it('健康线横幅带校准标注与低于线建议', async () => {
    api.publishReport.mockResolvedValue(REPORT);
    renderDrawer();
    await waitFor(() => { expect(screen.getByText(/通用基准初始值/)).toBeTruthy(); });
    expect(screen.getByText(/钩子重选/)).toBeTruthy();
    expect(screen.getByText(/剧一/)).toBeTruthy();
  });

  it('加载失败诚实显示错误，不伪装空表', async () => {
    api.publishReport.mockRejectedValue(new Error('boom'));
    renderDrawer();
    await waitFor(() => { expect(screen.getByText(/报告加载失败：boom/)).toBeTruthy(); });
  });

  it('空账如实提示去录入', async () => {
    api.publishReport.mockResolvedValue({ ...REPORT, rows: [], recorded: 0 });
    renderDrawer();
    await waitFor(() => { expect(screen.getByText(/暂无回流数据/)).toBeTruthy(); });
  });
});