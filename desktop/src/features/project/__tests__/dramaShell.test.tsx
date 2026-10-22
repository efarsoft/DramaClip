// @vitest-environment jsdom
/**
 * 剧空间壳（W3 档3 结构手术 §3.2-1 后）：单路由 /drama/:id，两区块上下堆叠。
 * 纪律：缺哪本账灰哪几盏灯不连坐；剧对不上账时横幅压顶但区块照渲染；
 * 在跑段进度用服务端数字；阶段条锚点 href 带 ?focus= 真参数。
 * current 由滚动位置派生——jsdom 无几何，滚动派生不在此测（真机三宽度验收覆盖）。
 */
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { JobInfo, Project } from '@dramaclip/protocol';
import { useJobsStore } from '../../../stores/jobs';
import { DramaShell } from '../DramaShell';

const api = vi.hoisted(() => ({
  get: vi.fn(),
  listWorks: vi.fn(),
}));

vi.mock('../../../services/client', () => ({
  projectApi: { get: api.get },
  listWorks: api.listWorks,
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

function analysisJob(partial: Partial<JobInfo> = {}): JobInfo {
  return {
    id: 'j1',
    type: 'analysis',
    ref_id: 'p1',
    status: 'running',
    progress: 40,
    label: null,
    error: null,
    created_at: 100,
    updated_at: 900,
    ...partial,
  };
}

function renderDrama(focus?: string): void {
  const path = focus === undefined ? '/drama/p1' : `/drama/p1?focus=${focus}`;
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/drama/:projectId"
          element={
            <DramaShell
              analysis={<div>分析域占位</div>}
              produce={<div>出片域占位</div>}
            />
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
  Element.prototype.scrollIntoView = () => undefined;
});

beforeEach(() => {
  api.get.mockResolvedValue({ project: P1, episodes: [] });
  api.listWorks.mockResolvedValue([]);
  // 任务账由 JobsFeed 写全局 store——测试直接喂快照，不走网络
  useJobsStore.setState({ jobs: [], available: true, error: null, serverTimeMs: 1000, drawerOpen: false });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('DramaShell 大阶段条（合一单路由）', () => {
  it('两区块同屏堆叠，四段锚点 href 都指向 /drama 带 focus', async () => {
    renderDrama();
    expect(await screen.findByRole('navigation', { name: '生产线阶段' })).toBeTruthy();
    expect(screen.getByText('分析域占位')).toBeTruthy();
    expect(screen.getByText('出片域占位')).toBeTruthy();
    for (const [stage, focus] of [
      ['① 进素材', 'intake'],
      ['② 分析', 'analysis'],
      ['③ 规划', 'planning'],
      ['④ 出片', 'export'],
    ] as const) {
      const link = screen.getByRole('link', { name: new RegExp(stage) });
      expect(link.getAttribute('href')).toBe(`/drama/p1?focus=${focus}`);
    }
  });

  it('聚合账缺席：①用硬数据点亮，②③点灰带「—」，不装绿', async () => {
    renderDrama();
    expect(await screen.findByText('① 进素材')).toBeTruthy();
    expect(screen.getByText('② 分析 —')).toBeTruthy();
    expect(screen.getByText('③ 规划 —')).toBeTruthy();
    expect(screen.getByText('④ 出片')).toBeTruthy();
  });

  it('失败任务：卡点句带 error 原文 + 去处理按钮', async () => {
    useJobsStore.getState().setSnapshot([analysisJob({ status: 'failed', progress: 0, error: 'Whisper 缺模型：转写无法开始' })], 1000);
    renderDrama();
    expect(await screen.findByText('卡在分析：Whisper 缺模型：转写无法开始')).toBeTruthy();
    expect(screen.getByRole('button', { name: /去处理/ })).toBeTruthy();
  });

  it('在跑任务：② 段显示服务端进度百分比，卡点句用 job.label', async () => {
    useJobsStore.getState().setSnapshot([analysisJob({ label: '第 3 集转写中' })], 5000);
    renderDrama();
    expect(await screen.findByText('② 分析 · 40%')).toBeTruthy();
    expect(screen.getByText('第 3 集转写中')).toBeTruthy();
    expect(screen.getByRole('button', { name: /去\s*看/ })).toBeTruthy();
  });
});

describe('DramaShell 缺账与导航', () => {
  it('任务账还没取到：② 灰且不装「没开跑」，④ 用成品硬数据照点', async () => {
    useJobsStore.setState({ jobs: [], available: false, error: null, serverTimeMs: null });
    renderDrama();
    expect(await screen.findByText(/阶段账不可用：任务账还没取到/)).toBeTruthy();
    expect(screen.getByText('② 分析 —')).toBeTruthy();
    expect(screen.getByText('④ 出片')).toBeTruthy();
    expect(screen.queryByText(/分析还没开跑/)).toBeNull();
  });

  it('任务账取失败：缺席原因原文上屏', async () => {
    useJobsStore.getState().setUnavailable('管道断开');
    renderDrama();
    expect(await screen.findByText(/阶段账不可用：任务账取不到：管道断开/)).toBeTruthy();
    expect(screen.getByText(/不是「没进行」/)).toBeTruthy();
  });

  it('成品账取不到：③④ 灰、② 照任务账走，卡点句沉默不硬凑', async () => {
    api.listWorks.mockRejectedValue(new Error('管道断开'));
    renderDrama();
    expect(await screen.findByText(/阶段账不可用：成品账取不到：管道断开/)).toBeTruthy();
    expect(screen.getByText('③ 规划 —')).toBeTruthy();
    expect(screen.getByText('④ 出片 —')).toBeTruthy();
    expect(screen.getByText('② 分析 —')).toBeTruthy();
    expect(screen.queryByText(/分析还没开跑/)).toBeNull();
  });

  it('剧对不上账：横幅给原因原文，阶段条缺席而非假灯，区块照渲染', async () => {
    api.get.mockRejectedValue(new Error('project not found: p1'));
    renderDrama();
    expect(await screen.findByText(/这部剧对不上账：project not found: p1/)).toBeTruthy();
    expect(screen.queryByRole('navigation', { name: '生产线阶段' })).toBeNull();
    expect(screen.getByText('分析域占位')).toBeTruthy();
    expect(screen.getByText('出片域占位')).toBeTruthy();
    expect(screen.getByRole('button', { name: /回剧库/ })).toBeTruthy();
  });
});
