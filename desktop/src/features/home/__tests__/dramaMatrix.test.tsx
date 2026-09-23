// @vitest-environment jsdom
/** 我的剧矩阵：行派生真值 + 聚合筛选 + 继续/卡点路由纪律（卷三图 1 / 意见 05）。 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { JobInfo, Project, WorkItem } from '@dramaclip/protocol';
import { DramaMatrix } from '../DramaMatrix';
import { buildMatrixRows, countByFilter, matchesFilter, sortRows } from '../matrixRows';

vi.mock('../../../services/client', () => ({
  mediaUrl: (path: string) => `media://${path}`,
}));

const NOW = 1_000_000_000;
const DAY = 86_400_000;

function project(id: string, name: string, partial: Partial<Project> = {}): Project {
  return {
    id,
    name,
    source_path: `D:/${id}`,
    status: 'ready',
    created_at: NOW - DAY,
    episode_count: 6,
    settings: {},
    ...partial,
  };
}

function work(id: string, projectId: string): WorkItem {
  return { id, project_id: projectId, project_name: projectId, output_path: `D:/${id}.mp4`, completed_at: NOW };
}

function job(partial: Partial<JobInfo>): JobInfo {
  return {
    id: 'j',
    type: 'analysis',
    ref_id: 'p1',
    status: 'running',
    progress: 40,
    label: null,
    error: null,
    created_at: NOW - DAY,
    updated_at: NOW,
    ...partial,
  };
}

// p1：分析失败卡住；p2：编剧在跑且已有两部成品。
const PROJECTS = [project('p1', '替嫁新娘'), project('p2', '赘婿归来')];
const WORKS = [work('w1', 'p2'), work('w2', 'p2')];
const JOBS = [
  job({ id: 'j1', ref_id: 'p1', status: 'failed', error: 'Whisper 缺模型：转写无法开始' }),
  job({ id: 'j2', ref_id: 'p2', type: 'narration', status: 'running', label: '写方案 2/9' }),
];

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
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('buildMatrixRows 行派生', () => {
  it('失败剧：failed 标记 + 卡点带 error 原文 + 路由去分析页', () => {
    const row = buildMatrixRows(PROJECTS, WORKS, JOBS, NOW).find((r) => r.project.id === 'p1');
    expect(row?.failed).toBe(true);
    expect(row?.running).toBe(false);
    expect(row?.note).toMatchObject({ tone: 'error', text: '卡在分析：Whisper 缺模型：转写无法开始' });
    expect(row?.cont).toEqual({ route: '/projects/p1/analysis', label: '继续分析' });
  });

  it('在跑剧：running 标记 + 卡点用 job.label 人读文本 + 继续去出片页', () => {
    const row = buildMatrixRows(PROJECTS, WORKS, JOBS, NOW).find((r) => r.project.id === 'p2');
    expect(row?.running).toBe(true);
    expect(row?.workCount).toBe(2);
    expect(row?.note).toMatchObject({ tone: 'action', text: '写方案 2/9' });
    expect(row?.cont).toEqual({ route: '/projects/p2/produce', label: '继续出片' });
  });

  it('聚合计数：全部/在跑/有失败/已出片各归各的', () => {
    const rows = buildMatrixRows(PROJECTS, WORKS, JOBS, NOW);
    expect(countByFilter(rows, 'all')).toBe(2);
    expect(countByFilter(rows, 'running')).toBe(1);
    expect(countByFilter(rows, 'failed')).toBe(1);
    expect(countByFilter(rows, 'shipped')).toBe(1);
    expect(rows.filter((r) => matchesFilter(r, 'shipped')).map((r) => r.project.id)).toEqual(['p2']);
  });

  it('排序：继续上次置顶，其余按最近动静倒序', () => {
    const rows = buildMatrixRows(PROJECTS, WORKS, JOBS, NOW);
    expect(sortRows(rows, 'p2')[0]?.project.id).toBe('p2');
    expect(sortRows(rows, null).every((r) => r.lastActivityMs >= NOW - DAY)).toBe(true);
  });
});

describe('DramaMatrix 渲染', () => {
  function matrix(onNavigate = vi.fn()) {
    render(
      <DramaMatrix
        projects={PROJECTS}
        works={WORKS}
        jobs={JOBS}
        serverTimeMs={NOW}
        etaLabel="预计还需 12 分"
        onNavigate={onNavigate}
      />,
    );
    return onNavigate;
  }

  it('一行一部剧：剧名 + 集数/成品数 meta + 阶段灯', async () => {
    matrix();
    expect(await screen.findByText('替嫁新娘')).toBeTruthy();
    expect(screen.getByText('赘婿归来')).toBeTruthy();
    expect(screen.getByText('6 集 · 2 部成品 · 刚刚')).toBeTruthy();
    expect(screen.getAllByText('② 分析 —').length).toBe(2);
  });

  it('聚合芯片显示计数，点击即筛选', async () => {
    matrix();
    expect(await screen.findByRole('button', { name: '全部 2' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '有失败 1' }));
    expect(screen.getByText('替嫁新娘')).toBeTruthy();
    expect(screen.queryByText('赘婿归来')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '全部 2' }));
    expect(screen.getByText('赘婿归来')).toBeTruthy();
  });
});

describe('DramaMatrix 继续与卡点', () => {
  function matrix(onNavigate = vi.fn()) {
    render(
      <DramaMatrix
        projects={PROJECTS}
        works={WORKS}
        jobs={JOBS}
        serverTimeMs={NOW}
        etaLabel="预计还需 12 分"
        onNavigate={onNavigate}
      />,
    );
    return onNavigate;
  }

  it('继续按钮去 cont 路由，整行点击同一目的地', async () => {
    const onNavigate = matrix();
    const continues = await screen.findAllByRole('button', { name: /继续出片|继续分析/ });
    const first = continues[0];
    if (first === undefined) throw new Error('矩阵行没有继续按钮');
    fireEvent.click(first);
    expect(onNavigate).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText('替嫁新娘'));
    expect(onNavigate).toHaveBeenLastCalledWith('/projects/p1/analysis');
  });

  it('卡点动作按钮走自己的路由，不触发整行跳转', async () => {
    const onNavigate = matrix();
    fireEvent.click(await screen.findByRole('button', { name: /去处理/ }));
    expect(onNavigate).toHaveBeenCalledTimes(1);
    expect(onNavigate).toHaveBeenCalledWith('/projects/p1/analysis');
  });

  it('继续上次：最近打开的剧置顶 + 芯片点名 + 铺底', async () => {
    window.localStorage.setItem(
      'dramaclip.last-drama',
      JSON.stringify({ id: 'p2', name: '赘婿归来', visitedAtMs: NOW }),
    );
    matrix();
    expect(await screen.findByText('继续上次')).toBeTruthy();
    const names = screen.getAllByText(/替嫁新娘|赘婿归来/).map((node) => node.textContent);
    expect(names[0]).toBe('赘婿归来');
  });

  it('筛到空时说清楚，不是一片白板', async () => {
    render(
      <DramaMatrix
        projects={[project('p1', '替嫁新娘')]}
        works={[]}
        jobs={[]}
        serverTimeMs={NOW}
        etaLabel=""
        onNavigate={vi.fn()}
      />,
    );
    fireEvent.click(await screen.findByRole('button', { name: '已出片 0' }));
    expect(screen.getByText('没有符合筛选的剧')).toBeTruthy();
  });
});
