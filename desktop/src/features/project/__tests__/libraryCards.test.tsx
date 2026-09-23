// @vitest-environment jsdom
/**
 * 剧库五要素卡与查询工具条（卷三图 2 / 意见 05）：
 * 封面+剧名+阶段灯+卡点句+meta 行齐活；聚合芯片即筛选器；缺账时灯灰、成品数「—」。
 */
import { App as AntdApp } from 'antd';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Project, WorkItem } from '@dramaclip/protocol';
import { ProjectsPage } from '../ProjectsPage';
import { applyQuery, buildLibraryRows } from '../libraryRows';
import type { LibraryFacts } from '../useLibraryFacts';

const api = vi.hoisted(() => ({
  list: vi.fn(),
  ensureCovers: vi.fn(),
  listWorks: vi.fn(),
  jobsList: vi.fn(),
}));

vi.mock('../../../services/client', () => ({
  projectApi: {
    list: api.list,
    ensureCovers: api.ensureCovers,
    create: vi.fn(),
    remove: vi.fn(),
    rename: vi.fn(),
    duplicate: vi.fn(),
    scanEpisodes: vi.fn(),
  },
  listWorks: api.listWorks,
  jobsApi: { list: api.jobsList },
  pickFolder: vi.fn(),
  mediaUrl: (path: string) => `dramaclip://local/${path}`,
}));

function project(id: string, name: string, over: Partial<Project> = {}): Project {
  return {
    id,
    name,
    source_path: `D:\\素材\\${name}`,
    status: 'active',
    created_at: 100,
    episode_count: 32,
    settings: {},
    ...over,
  };
}

const WORK: WorkItem = {
  id: 'w1',
  project_id: 'p1',
  project_name: '替嫁新娘',
  output_path: 'D:/out/w1.mp4',
  completed_at: 900,
};

const FAILED_JOB = {
  id: 'j1',
  type: 'analysis',
  ref_id: 'p1',
  status: 'failed',
  progress: 0,
  label: null,
  error: 'Whisper 缺模型：转写无法开始',
  created_at: 100,
  updated_at: 1000,
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
  api.list.mockResolvedValue([project('p1', '替嫁新娘'), project('p2', '赘婿归来', { created_at: 200 })]);
  api.ensureCovers.mockResolvedValue({ ok: true, generated: 0 });
  api.listWorks.mockResolvedValue([WORK]);
  api.jobsList.mockResolvedValue({ jobs: [FAILED_JOB], server_time_ms: 1000 });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function page(): void {
  render(
    <MemoryRouter>
      <AntdApp>
        <ProjectsPage />
      </AntdApp>
    </MemoryRouter>,
  );
}

describe('剧库页渲染', () => {
  it('首启空态：三步说清楚 + 唯一 primary 在空态里', async () => {
    api.list.mockResolvedValue([]);
    page();
    expect(await screen.findByText('还没有剧')).toBeTruthy();
    expect(screen.getByText('自动扫描素材')).toBeTruthy();
    expect(screen.getByText('分析后出片')).toBeTruthy();
    // 步骤①的标题与按钮同词：数按钮即可——空态下 header 的 primary 已让位，全屏唯一
    expect(screen.getAllByRole('button', { name: /新建项目/ }).length).toBe(1);
  });

  it('五要素卡：剧名 + 阶段灯 + 卡点原文 + meta 行', async () => {
    page();
    expect(await screen.findByText('替嫁新娘')).toBeTruthy();
    expect(screen.getByText('32 集 · 1 部成品')).toBeTruthy();
    expect(screen.getByText('卡在分析：Whisper 缺模型：转写无法开始')).toBeTruthy();
    expect(screen.getAllByText('② 分析 —').length).toBe(2);
    expect(screen.getByRole('button', { name: /去处理/ })).toBeTruthy();
  });

  it('聚合芯片即筛选器：点了就收窄', async () => {
    page();
    await screen.findByText('替嫁新娘');
    fireEvent.click(screen.getByRole('button', { name: '有失败 1' }));
    expect(screen.getByText('替嫁新娘')).toBeTruthy();
    expect(screen.queryByText('赘婿归来')).toBeNull();
  });

  it('搜剧名：包含即中，大小写不敏感由查询层负责', async () => {
    page();
    await screen.findByText('替嫁新娘');
    fireEvent.change(screen.getByPlaceholderText('搜剧名'), { target: { value: '赘婿' } });
    expect(screen.getByText('赘婿归来')).toBeTruthy();
    expect(screen.queryByText('替嫁新娘')).toBeNull();
  });

  it('排序切到最近创建：created_at 大的在前', async () => {
    page();
    await screen.findByText('替嫁新娘');
    fireEvent.click(screen.getByText('最近创建'));
    const names = screen.getAllByText(/替嫁新娘|赘婿归来/).map((node) => node.textContent);
    expect(names[0]).toBe('赘婿归来');
  });

  it('成品与任务账取不到：警告横幅 + 成品数「—」+ 灯点灰不装绿', async () => {
    api.listWorks.mockRejectedValue(new Error('管道断开'));
    api.jobsList.mockRejectedValue(new Error('管道断开'));
    page();
    expect(await screen.findByText(/成品与任务账取不到/)).toBeTruthy();
    expect(screen.getByText(/成品账：管道断开/)).toBeTruthy();
    expect(screen.getAllByText('32 集 · — 部成品').length).toBe(2);
    expect(screen.getAllByText('② 分析 —').length).toBe(2);
    expect(screen.queryByText(/卡在分析/)).toBeNull();
  });
});

describe('libraryRows 纯函数', () => {
  const noFacts: LibraryFacts = { works: null, jobs: null, serverTimeMs: null, factsError: 'x', reload: () => Promise.resolve() };

  it('账本缺席：factsMissing=true，进素材仍用硬数据，其余全灰', () => {
    const { rows, factsMissing } = buildLibraryRows([project('p1', 'A', { episode_count: 4 })], noFacts);
    expect(factsMissing).toBe(true);
    expect(rows[0]?.stages.intake).toBe('done');
    expect(rows[0]?.stages.analysis).toBe('unknown');
    expect(rows[0]?.note).toBeNull();
  });

  it('applyQuery：筛选 + 搜索 + 排序一次过', () => {
    const { rows } = buildLibraryRows(
      [project('p1', 'Beta', { created_at: 100 }), project('p2', 'alpha', { created_at: 200 })],
      { works: [], jobs: [], serverTimeMs: 1000, factsError: null, reload: () => Promise.resolve() },
    );
    expect(applyQuery(rows, { filter: 'all', search: 'alph', sort: 'created' }).map((r) => r.project.id)).toEqual(['p2']);
    expect(applyQuery(rows, { filter: 'shipped', search: '', sort: 'activity' })).toEqual([]);
    expect(applyQuery(rows, { filter: 'all', search: '', sort: 'name' }).map((r) => r.project.name)).toEqual(['alpha', 'Beta']);
  });
});
