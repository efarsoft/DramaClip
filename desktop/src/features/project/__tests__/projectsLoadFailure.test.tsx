// @vitest-environment jsdom
/**
 * 项目列表失败态（附录 A 行 2 的永久转圈根治，卷三意见 01 第一刀）。
 * 纪律：取不到 ≠ 一直在取——原文上屏 + 真重试；旧数据在手时横幅压顶、网格保留。
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { App as AntdApp } from 'antd';
import { MemoryRouter } from 'react-router-dom';
import type { Project } from '@dramaclip/protocol';
import { ProjectsPage } from '../ProjectsPage';

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

function project(over: Partial<Project> = {}): Project {
  return {
    id: 'p1',
    name: '替嫁新娘',
    source_path: 'D:\\素材\\替嫁新娘',
    status: 'active',
    created_at: 0,
    episode_count: 32,
    settings: {},
    ...over,
  };
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
      // 浮层尺寸由真浏览器观察，这里什么都不必做
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
    <MemoryRouter>
      <AntdApp>
        <ProjectsPage />
      </AntdApp>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  api.list.mockResolvedValue([]);
  api.ensureCovers.mockResolvedValue({ ok: true, generated: 0 });
  api.listWorks.mockResolvedValue([]);
  api.jobsList.mockResolvedValue({ jobs: [], server_time_ms: 0 });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('项目列表加载失败', () => {
  it('失败原文上屏 + 真重试按钮，不再永久转圈', async () => {
    // 补拍挂起：本例只考察首拉失败的渲染，不让 ensureCovers→reload 链搅局
    api.ensureCovers.mockReturnValue(new Promise(() => undefined));
    api.list.mockRejectedValue(new Error('管道断开'));
    page();

    expect(await screen.findByText(/项目列表加载失败：管道断开/)).toBeTruthy();
    // antd 会给两字按钮插空格（「重 试」），按可及名正则匹配
    expect(screen.getByRole('button', { name: /重\s*试/ })).toBeTruthy();
    expect(document.querySelector('.ant-card-loading')).toBeNull();
  });

  it('点重试真重拉：成功后横幅消失、剧卡出现', async () => {
    api.ensureCovers.mockReturnValue(new Promise(() => undefined));
    api.list.mockRejectedValueOnce(new Error('管道断开'));
    page();
    await screen.findByText(/项目列表加载失败/);

    api.list.mockResolvedValue([project()]);
    fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }));

    expect(await screen.findByText('替嫁新娘')).toBeTruthy();
    expect(screen.queryByText(/项目列表加载失败/)).toBeNull();
  });

  it('旧数据在手时刷新失败：列表保留，横幅写明「可能已过期」', async () => {
    // 时序：首拉成功 → ensureCovers 完成触发 reload → reload 失败
    api.list.mockResolvedValueOnce([project()]).mockRejectedValueOnce(new Error('服务重启中'));
    page();

    expect(await screen.findByText(/可能已过期/)).toBeTruthy();
    expect(screen.getByText('替嫁新娘')).toBeTruthy();
  });

  it('封面补拍失败说出现象与后果，不静默吞', async () => {
    api.ensureCovers.mockRejectedValue(new Error('ffmpeg 崩了'));
    page();

    expect(await screen.findByText(/部分封面补拍未完成/)).toBeTruthy();
  });
});
