// @vitest-environment jsdom
/**
 * 成片详情页（09-10 §4.5）：追溯链（角度金标签 + 取材集区间 + 去方案区）、
 * 自检分区（未检可补测）、完整路径上屏；方案已删如实说断链。
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { App as AntdApp } from 'antd';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { useUiStore } from '../../../stores/ui';
import { WorksDetailPage } from '../WorksDetailPage';

const api = vi.hoisted(() => ({
  get: vi.fn(),
  selfcheck: vi.fn(),
  projectGet: vi.fn(),
  rpc: vi.fn(),
  generate: vi.fn(),
}));

vi.mock('../../../services/client', () => ({
  exportApi: { get: api.get, selfcheck: api.selfcheck },
  projectApi: { get: api.projectGet },
  rpc: api.rpc,
  titlesApi: { generate: api.generate },
  mediaUrl: (path: string) => `dramaclip://local/${path}`,
  revealInFolder: vi.fn().mockResolvedValue({ ok: true }),
  pickFolder: vi.fn().mockResolvedValue(null),
  copyFiles: vi.fn(),
}));

const JOB = {
  id: 'w1',
  project_id: 'p1',
  status: 'completed',
  progress: 100,
  created_at: 0,
  output_path: 'D:/data/outputs/p1/film_a1b2c3.mp4',
  narration_plan_id: 'plan1',
  narration_mode: 'full_narration',
  duration_s: 134,
  size_bytes: 268435456,
  completed_at: 1758600000000,
  selfcheck: null,
  selfcheck_state: null,
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

function page(): void {
  render(
    <MemoryRouter initialEntries={['/works/w1']}>
      <AntdApp>
        <Routes>
          <Route path="/works/:exportId" element={<WorksDetailPage />} />
        </Routes>
      </AntdApp>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  useUiStore.getState().setServiceState('ready');
  api.get.mockResolvedValue(JOB);
  api.projectGet.mockResolvedValue({
    project: { id: 'p1', name: '替嫁新娘' },
    episodes: [
      { id: 'e1', episode_number: 4 },
      { id: 'e2', episode_number: 11 },
    ],
  });
  api.rpc.mockResolvedValue({
    plan: {
      titles: [],
      angle: '替身真相',
      episode_ids: ['e1', 'e2'],
      plan_data: { narration_texts: [] },
    },
  });
  api.selfcheck.mockResolvedValue({ ok: true, job_id: 'j1', queued: 1 });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('追溯链', () => {
  it('角度金标签 + 取材集区间 + 完整路径', async () => {
    page();
    expect(await screen.findByText('替身真相')).toBeTruthy();
    expect(await screen.findByText('取材 EP04–EP11')).toBeTruthy();
    expect(screen.getByText('D:/data/outputs/p1/film_a1b2c3.mp4')).toBeTruthy();
    expect(screen.getByRole('button', { name: /去方案区/ }).hasAttribute('disabled')).toBe(false);
  });

  it('方案已删：如实说断链，去方案区禁用（缺席而非假按钮）', async () => {
    api.get.mockResolvedValue({ ...JOB, narration_plan_id: undefined });
    page();
    expect(await screen.findByText('方案已删除，追溯链断')).toBeTruthy();
    expect(screen.getByRole('button', { name: /去方案区/ }).hasAttribute('disabled')).toBe(true);
  });
});

describe('自检分区', () => {
  it('从未自检：说明文案 + 补测此片真发 RPC', async () => {
    page();
    // 四项徽章的度量原文都如实写「从未自检」，页脚另有一句操作指引
    expect(await screen.findAllByText('从未自检')).toHaveLength(4);
    expect(screen.getByText(/从未自检——「补测此片」/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /补测此片/ }));
    await vi.waitFor(() => {
      expect(api.selfcheck).toHaveBeenCalledWith(['w1']);
    });
  });
});
