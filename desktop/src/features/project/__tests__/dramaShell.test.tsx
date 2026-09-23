// @vitest-environment jsdom
/**
 * 剧空间壳（卷三意见 06 第一刀）：只读大阶段条 + Outlet，域页零触碰。
 * 纪律：账本缺席灯点灰不装绿；剧对不上账时横幅压顶但 Outlet 照渲染（壳是加法不连坐）。
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Project } from '@dramaclip/protocol';
import { DramaShell } from '../DramaShell';

const api = vi.hoisted(() => ({
  list: vi.fn(),
  listWorks: vi.fn(),
  jobsList: vi.fn(),
}));

vi.mock('../../../services/client', () => ({
  projectApi: { list: api.list },
  listWorks: api.listWorks,
  jobsApi: { list: api.jobsList },
  mediaUrl: (path: string) => `dramaclip://local/${path}`,
}));

const P1: Project = {
  id: 'p1',
  name: '替嫁新娘',
  source_path: 'D:\\素材\\替嫁新娘',
  status: 'active',
  created_at: 100,
  episode_count: 6,
  settings: {},
};

function renderAt(path: string): void {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/projects/:projectId/analysis"
          element={
            <DramaShell>
              <div>分析域占位</div>
            </DramaShell>
          }
        />
        <Route
          path="/projects/:projectId/produce"
          element={
            <DramaShell>
              <div>出片域占位</div>
            </DramaShell>
          }
        />
      </Routes>
    </MemoryRouter>,
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
      // 尺寸观察交给真浏览器
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

beforeEach(() => {
  api.list.mockResolvedValue([P1]);
  api.listWorks.mockResolvedValue([]);
  api.jobsList.mockResolvedValue({ jobs: [], server_time_ms: 1000 });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('DramaShell 只读阶段条', () => {
  it('四段全在场，当前段 aria-current=step，域页原样渲染', async () => {
    renderAt('/projects/p1/analysis');
    expect(await screen.findByRole('navigation', { name: '生产线阶段' })).toBeTruthy();
    expect(screen.getByRole('link', { name: /① 进素材/ })).toBeTruthy();
    expect(screen.getByRole('link', { name: /② 分析/ }).getAttribute('aria-current')).toBe('step');
    expect(screen.getByRole('link', { name: /③ 规划/ })).toBeTruthy();
    expect(screen.getByRole('link', { name: /④ 出片/ })).toBeTruthy();
    expect(screen.getByText('分析域占位')).toBeTruthy();
  });

  it('聚合账缺席：①用硬数据点亮，②③点灰带「—」，不装绿', async () => {
    renderAt('/projects/p1/analysis');
    expect(await screen.findByText('① 进素材')).toBeTruthy();
    expect(screen.getByText('② 分析 —')).toBeTruthy();
    expect(screen.getByText('③ 规划 —')).toBeTruthy();
    expect(screen.getByText('④ 出片')).toBeTruthy();
  });

  it('失败任务：卡点句带 error 原文 + 去处理按钮', async () => {
    api.jobsList.mockResolvedValue({
      jobs: [
        {
          id: 'j1',
          type: 'analysis',
          ref_id: 'p1',
          status: 'failed',
          progress: 0,
          label: null,
          error: 'Whisper 缺模型：转写无法开始',
          created_at: 100,
          updated_at: 900,
        },
      ],
      server_time_ms: 1000,
    });
    renderAt('/projects/p1/analysis');
    expect(await screen.findByText('卡在分析：Whisper 缺模型：转写无法开始')).toBeTruthy();
    expect(screen.getByRole('button', { name: /去处理/ })).toBeTruthy();
  });

  it('剧对不上账：横幅给原因原文，阶段条缺席而非假灯，Outlet 照渲染', async () => {
    api.list.mockResolvedValue([]);
    renderAt('/projects/p1/analysis');
    expect(await screen.findByText(/这部剧对不上账：剧列表里没有这部剧：它可能已被删除/)).toBeTruthy();
    expect(screen.queryByRole('navigation', { name: '生产线阶段' })).toBeNull();
    expect(screen.getByText('分析域占位')).toBeTruthy();
    expect(screen.getByRole('button', { name: /回剧库/ })).toBeTruthy();
  });

  it('成品账取不到：说清哪本账缺了，灯灰且声明「取不到≠没进行」', async () => {
    api.listWorks.mockRejectedValue(new Error('管道断开'));
    renderAt('/projects/p1/analysis');
    expect(await screen.findByText(/阶段账不可用：成品账取不到/)).toBeTruthy();
    expect(screen.getByText(/不是「没进行」/)).toBeTruthy();
    expect(screen.getByText('② 分析 —')).toBeTruthy();
  });

  it('段点击真跳转：④ 带路到出片页，当前段高亮跟到 ③', async () => {
    renderAt('/projects/p1/analysis');
    fireEvent.click(await screen.findByRole('link', { name: /④ 出片/ }));
    expect(await screen.findByText('出片域占位')).toBeTruthy();
    expect(screen.getByRole('link', { name: /③ 规划/ }).getAttribute('aria-current')).toBe('step');
  });
});
