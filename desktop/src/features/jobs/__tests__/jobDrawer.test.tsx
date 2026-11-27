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
  clearFinished: vi.fn(),
  projectList: vi.fn(),
  modelsList: vi.fn(),
  modelDownload: vi.fn(),
  analysisStart: vi.fn(),
}));

vi.mock('../../../services/client', () => ({
  jobsApi: { list: api.listJobs, get: vi.fn(), cancel: api.cancel, clearFinished: api.clearFinished },
  projectApi: { list: api.projectList },
  modelsApi: { list: api.modelsList, download: api.modelDownload },
  analysisApi: { start: api.analysisStart },
  appVersion: vi.fn(() => Promise.resolve('0.2.0')),
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

  it('失败行就地重试（W12）：下载类走 models.download、分析类走 analysis.start', async () => {
    api.modelDownload.mockResolvedValue({ job_id: 'jd2' });
    api.analysisStart.mockResolvedValue({ job_id: 'ja2' });
    const failedDownload = job({ id: 'jd', type: 'model_download', ref_id: 'kokoro', status: 'failed', progress: 0, error: '服务中断', updated_at: 900_000 });
    const failedAnalysis = job({ id: 'ja', type: 'analysis', ref_id: 'p1', status: 'failed', progress: 0, error: '分析失败', updated_at: 900_000 });
    useJobsStore.setState({ jobs: [failedDownload, failedAnalysis], available: true, serverTimeMs: SERVER_NOW, drawerOpen: true });
    drawer();

    // antd 给两字按钮插空格（「重 试」），按可及名正则匹配
    const retryButtons = await screen.findAllByRole('button', { name: /重\s*试/ });
    expect(retryButtons.length).toBe(2);
    const [dlButton, analysisButton] = retryButtons;
    if (dlButton === undefined || analysisButton === undefined) {
      throw new Error('两个失败行都该有重试按钮');
    }
    fireEvent.click(dlButton);
    await waitFor(() => {
      expect(api.modelDownload).toHaveBeenCalledWith('kokoro');
    });
    fireEvent.click(analysisButton);
    await waitFor(() => {
      expect(api.analysisStart).toHaveBeenCalledWith('p1');
    });
  });

  it('export 失败行不显示就地重试（依赖页面上下文），保持「去处理」路由', async () => {
    const failedExport = job({ id: 'je', type: 'export', ref_id: 'p1', status: 'failed', progress: 0, error: '导出失败', updated_at: 900_000 });
    useJobsStore.setState({ jobs: [failedExport], available: true, serverTimeMs: SERVER_NOW, drawerOpen: true });
    drawer();

    expect(await screen.findByText('导出失败')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /重\s*试/ })).toBeNull();
    expect(screen.getByRole('button', { name: '去处理' })).toBeTruthy();
  });
});

describe('会话留痕（notifyLog）', () => {
  it('每条入列即得自增 id；滑出窗口后留存条目的 id 保持原值（key 钉内容身份）', () => {
    useJobsStore.setState({ notifyLog: [] });
    const entry = { jobId: null, level: 'info', message: 'x', at: 1 };
    useJobsStore.getState().appendNotifyLog(entry);
    useJobsStore.getState().appendNotifyLog(entry);
    const [firstId, secondId] = useJobsStore.getState().notifyLog.map((item) => item.id);
    if (firstId === undefined || secondId === undefined) throw new Error('两条都该在窗内');
    expect(secondId).toBe(firstId + 1);

    // 塞爆窗口（上限 200）再追加 202 条：204 个序号里最后 200 个留窗——
    // 留下的 id 是连续自增的原值，不随数组前移而漂
    for (let i = 0; i < 202; i += 1) {
      useJobsStore.getState().appendNotifyLog({ jobId: null, level: 'info', message: `m${String(i)}`, at: i });
    }
    const log = useJobsStore.getState().notifyLog;
    expect(log).toHaveLength(200);
    const oldest = log[0];
    const newest = log[199];
    if (oldest === undefined || newest === undefined) throw new Error('窗口该是满 200 条');
    expect(oldest.id).toBe(secondId + 3);
    expect(newest.id).toBe(secondId + 202);
  });

  it('留痕上屏：jobId 截前 6 位、warn 着色内容照登', async () => {
    useJobsStore.setState({ jobs: [], available: true, serverTimeMs: SERVER_NOW, drawerOpen: true, notifyLog: [] });
    useJobsStore.getState().appendNotifyLog({ jobId: 'jabc123456', level: 'info', message: '转写开始', at: 1 });
    useJobsStore.getState().appendNotifyLog({ jobId: null, level: 'warn', message: 'OCR 缺一页', at: 2 });
    drawer();

    expect(await screen.findByText('[jabc12] 转写开始')).toBeTruthy();
    expect(screen.getByText('OCR 缺一页')).toBeTruthy();
    expect(screen.getByText(/本会话留痕/)).toBeTruthy();
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

  it('后台页不打扰：hidden 时 tick 空转不发包，回前台立即补一发', async () => {
    useUiStore.setState({ serviceState: 'ready' });
    api.listJobs.mockResolvedValue({ jobs: [], server_time_ms: SERVER_NOW });
    const setHidden = (value: boolean): void => {
      Object.defineProperty(document, 'hidden', { configurable: true, value });
    };
    setHidden(true);
    feed();
    // 初始 tick 与几拍定时器都过去了，仍然零请求
    await new Promise((resolve) => {
      setTimeout(resolve, 30);
    });
    expect(api.listJobs).not.toHaveBeenCalled();

    setHidden(false);
    fireEvent(document, new Event('visibilitychange'));
    await waitFor(() => {
      expect(api.listJobs).toHaveBeenCalledTimes(1);
    });
    setHidden(false); // 复位，别污染后续用例
  });
});

describe('任务中心清空记录', () => {
  it('有已结束记录时给「清空记录」，量化确认后清掉，在跑的不动', async () => {
    useUiStore.setState({ serviceState: 'ready' });
    useJobsStore.setState({
      jobs: [RUNNING_EXPORT, FAILED_JOB],
      available: true,
      serverTimeMs: SERVER_NOW,
    });
    api.clearFinished.mockResolvedValue({ deleted: 1 });
    render(
      <MemoryRouter>
        <JobDrawer />
      </MemoryRouter>,
    );
    useJobsStore.setState({ drawerOpen: true });

    fireEvent.click(await screen.findByText('清空记录'));
    fireEvent.click(await screen.findByText('清 空'));
    await waitFor(() => {
      expect(api.clearFinished).toHaveBeenCalledTimes(1);
    });
  });
});

describe('StatusBar 任务段', () => {
  it('有在跑/失败：计数角标，点击开抽屉', async () => {
    useUiStore.setState({ serviceState: 'ready' });
    useJobsStore.setState({ jobs: [RUNNING_EXPORT, FAILED_JOB], available: true, serverTimeMs: SERVER_NOW });
    render(<StatusBar />);

    expect(await screen.findByText(/在跑 1/)).toBeTruthy();
    expect(screen.getByText(/进度 62\s*%/)).toBeTruthy();  // 卷二 #18：最高优先级在跑 job 的 %
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
