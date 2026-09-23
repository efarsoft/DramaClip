// @vitest-environment jsdom
/**
 * 任务中心三件套（P-A）：抽屉渲染纪律 / JobsFeed 门控轮询 / StatusBar 任务角标。
 * 钉的是行为不是像素：取不到 ≠ 空列表、失败原文全量上屏、取消被拒说 reason。
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import type { JobInfo } from '@dramaclip/protocol';
import { StatusBar } from '../../../components/layout/StatusBar';
import { useJobsStore } from '../../../stores/jobs';
import { useUiStore } from '../../../stores/ui';
import { JobDrawer } from '../JobDrawer';
import { JobsFeed } from '../JobsFeed';

const api = vi.hoisted(() => ({
  listJobs: vi.fn(),
  cancel: vi.fn(),
  projectList: vi.fn(),
  modelsList: vi.fn(),
}));

vi.mock('../../../services/client', () => ({
  jobsApi: { list: api.listJobs, get: vi.fn(), cancel: api.cancel },
  projectApi: { list: api.projectList },
  modelsApi: { list: api.modelsList },
  appVersion: vi.fn(() => Promise.resolve('1.1.0-RC')),
  systemApi: { health: vi.fn(() => Promise.resolve({})) },
}));

function job(over: Partial<JobInfo> = {}): JobInfo {
  return {
    id: 'j1',
    type: 'analysis',
    ref_id: 'p1',
    status: 'running',
    progress: 40,
    created_at: 1_000,
    updated_at: 2_000,
    ...over,
  };
}

const SERVER_NOW = 1_000_000;
const FAILED_JOB = job({
  id: 'jf',
  status: 'failed',
  progress: 0,
  error: 'Whisper 缺模型：转写无法开始',
  updated_at: 900_000,
});
const RUNNING_EXPORT = job({
  id: 'jr',
  type: 'export',
  ref_id: 'e1',
  status: 'running',
  progress: 62,
  label: '段切割 3/7',
  created_at: SERVER_NOW - 252_000,
  updated_at: SERVER_NOW,
});

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
  useJobsStore.setState({ jobs: [], available: false, error: null, serverTimeMs: null, drawerOpen: false });
  useUiStore.setState({ serviceState: 'starting' });
  api.projectList.mockResolvedValue([
    { id: 'p1', name: '替嫁新娘', source_path: 'D:\\素材', status: 'active', created_at: 0, episode_count: 32, settings: {} },
  ]);
  api.modelsList.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function drawer(): void {
  render(
    <MemoryRouter>
      <JobDrawer />
    </MemoryRouter>,
  );
}

describe('JobDrawer', () => {
  it('取不到任务时如实报原因，不装成空列表', async () => {
    useJobsStore.setState({ available: false, error: '管道断开', drawerOpen: true });
    drawer();
    expect(await screen.findByText(/任务状态取不到/)).toBeTruthy();
    expect(screen.getByText(/管道断开/)).toBeTruthy();
    expect(screen.queryByText('没有符合条件的任务')).toBeNull();
  });

  it('失败行 error 原文全量上屏且给「去处理」；运行行给阶段词与取消', async () => {
    useJobsStore.setState({
      jobs: [FAILED_JOB, RUNNING_EXPORT],
      available: true,
      serverTimeMs: SERVER_NOW,
      drawerOpen: true,
    });
    drawer();

    expect(await screen.findByText('Whisper 缺模型：转写无法开始')).toBeTruthy();
    expect(screen.getByRole('button', { name: '去处理' })).toBeTruthy();
    // 主体名册加载后 ref_id 翻成剧名
    expect(await screen.findByText(/替嫁新娘/)).toBeTruthy();
    expect(screen.getByText(/段切割 3\/7/)).toBeTruthy();
    // antd 给两字按钮插空格（「取 消」），按可及名正则匹配
    expect(screen.getByRole('button', { name: /取\s*消/ })).toBeTruthy();
    // 已进行 = server_time_ms − created_at（4分12秒），不用本机时钟
    expect(screen.getByText(/4分12秒/)).toBeTruthy();
  });

  it('取消被拒：服务端 reason 原样说出来，不谎报已取消', async () => {
    useJobsStore.setState({ jobs: [RUNNING_EXPORT], available: true, serverTimeMs: SERVER_NOW, drawerOpen: true });
    api.cancel.mockResolvedValue({ job_id: 'jr', cancelling: false, reason: '任务不可中断' });
    drawer();

    fireEvent.click(await screen.findByRole('button', { name: /取\s*消/ }));
    expect(await screen.findByText(/无法取消：任务不可中断/)).toBeTruthy();
    expect(api.cancel).toHaveBeenCalledWith('jr');
  });

  it('取消受理：明示等任务在检查点退出，终态由轮询带回', async () => {
    useJobsStore.setState({ jobs: [RUNNING_EXPORT], available: true, serverTimeMs: SERVER_NOW, drawerOpen: true });
    api.cancel.mockResolvedValue({ job_id: 'jr', cancelling: true });
    drawer();

    fireEvent.click(await screen.findByRole('button', { name: /取\s*消/ }));
    expect(await screen.findByText(/已请求取消，等任务在检查点退出/)).toBeTruthy();
  });
});

describe('JobsFeed（门控轮询）', () => {
  function feed(): void {
    render(
      <MemoryRouter>
        <JobsFeed />
      </MemoryRouter>,
    );
  }

  it('服务未就绪不发 RPC', async () => {
    feed();
    await waitFor(() => {
      expect(api.listJobs).not.toHaveBeenCalled();
    });
  });

  it('就绪后拉一次，快照进 store', async () => {
    useUiStore.setState({ serviceState: 'ready' });
    api.listJobs.mockResolvedValue({ jobs: [RUNNING_EXPORT], server_time_ms: SERVER_NOW });
    feed();
    await waitFor(() => {
      expect(useJobsStore.getState().available).toBe(true);
    });
    expect(useJobsStore.getState().serverTimeMs).toBe(SERVER_NOW);
    expect(useJobsStore.getState().jobs).toHaveLength(1);
  });

  it('拉取失败：记成取不到并留原因原文，不清成空列表', async () => {
    useUiStore.setState({ serviceState: 'ready' });
    useJobsStore.setState({ jobs: [RUNNING_EXPORT], available: true });
    api.listJobs.mockRejectedValue(new Error('管道断开'));
    feed();
    await waitFor(() => {
      expect(useJobsStore.getState().available).toBe(false);
    });
    expect(useJobsStore.getState().error).toBe('管道断开');
  });
});

describe('StatusBar 任务段', () => {
  it('有在跑/失败：计数角标，点击开抽屉', async () => {
    useUiStore.setState({ serviceState: 'ready' });
    useJobsStore.setState({ jobs: [RUNNING_EXPORT, FAILED_JOB], available: true, serverTimeMs: SERVER_NOW });
    render(<StatusBar />);

    expect(await screen.findByText(/在跑 1/)).toBeTruthy();
    expect(screen.getByText(/失败 1/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /在跑 1/ }));
    expect(useJobsStore.getState().drawerOpen).toBe(true);
  });

  it('空闲：明说没有在跑任务，不留空白', async () => {
    useUiStore.setState({ serviceState: 'ready' });
    useJobsStore.setState({ jobs: [], available: true, serverTimeMs: SERVER_NOW });
    render(<StatusBar />);
    expect(await screen.findByText('没有在跑任务')).toBeTruthy();
  });

  it('取不到：显示「—」不假装 0', async () => {
    useUiStore.setState({ serviceState: 'ready' });
    useJobsStore.setState({ available: false, error: '管道断开' });
    render(<StatusBar />);
    expect(await screen.findByText('任务 · —')).toBeTruthy();
  });
});
