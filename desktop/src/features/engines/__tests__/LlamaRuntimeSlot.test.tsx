// @vitest-environment jsdom
/** 视觉推理运行时安装槽接线回归（0.2.5 主题一 1.1）。
 *
 * 未装 → 一键下载入口现身；作业 completed → 槽消失（装完不驻留）；
 * 作业 failed → 失败原话常驻 + 重试入口。探测失败说「未知」，不冒充「未安装」。
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { JobInfo } from '@dramaclip/protocol';
import { jobsApi, llamaRuntimeApi } from '../../../services/client';
import { useUiStore } from '../../../stores/ui';
import { LlamaRuntimeSlot } from '../LlamaRuntimeSlot';

const jobInfo = (over: Partial<JobInfo>): JobInfo => ({
  id: 'j-llama',
  type: 'llama_runtime',
  ref_id: null,
  status: 'running',
  progress: 0,
  created_at: 0,
  updated_at: 0,
  ...over,
});

vi.mock('../../../services/client', () => ({
  jobsApi: { get: vi.fn(() => Promise.resolve({ job: jobInfo({}) })) },
  llamaRuntimeApi: {
    status: vi.fn(() => Promise.resolve({ installed: false, exe: '', tag: '', variant: '', files: [] })),
    install: vi.fn(() => Promise.resolve({ job_id: 'j-llama' })),
  },
}));

function Harness(): React.ReactElement {
  return <LlamaRuntimeSlot />;
}

describe('LlamaRuntimeSlot', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useUiStore.setState({ serviceState: 'ready' });
  });
  afterEach(() => {
    cleanup();
  });

  it('未安装时现身一键下载，点击起作业并轮询', async () => {
    render(<Harness />);
    const button = await screen.findByRole('button', { name: /下载运行时/ });
    fireEvent.click(button);
    expect(llamaRuntimeApi.install).toHaveBeenCalledTimes(1);
    // 轮询间隔 3s：waitFor 时限要盖过它
    await waitFor(
      () => {
        expect(jobsApi.get).toHaveBeenCalledWith('j-llama');
      },
      { timeout: 4500 },
    );
  });

  it('作业失败时失败原话常驻并给出重试入口', async () => {
    vi.mocked(jobsApi.get).mockResolvedValue({
      job: jobInfo({ status: 'failed', error: '全部源下载失败: X' }),
    });
    render(<Harness />);
    fireEvent.click(await screen.findByRole('button', { name: /下载运行时/ }));
    await waitFor(
      () => {
        expect(screen.getByText(/安装失败：全部源下载失败/)).toBeTruthy();
      },
      { timeout: 4500 },
    );
    expect(screen.getByRole('button', { name: /重试下载/ })).toBeTruthy();
  });

  it('探测失败说状态未知，不冒充未安装', async () => {
    vi.mocked(llamaRuntimeApi.status).mockRejectedValue(new Error('服务掉线'));
    render(<Harness />);
    await waitFor(() => {
      expect(screen.getByText(/状态未知/)).toBeTruthy();
    });
    expect(screen.queryByRole('button', { name: /下载运行时/ })).toBeNull();
  });
});
