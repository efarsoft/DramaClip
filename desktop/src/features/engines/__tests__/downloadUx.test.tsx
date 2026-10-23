// 下载 UX：进度三件套上屏、failed 态可见且可重试（附录 B②）、下载中给取消（规格 H3 §3.1.2）、
// 事件解析不瞎猜缺字段——每一条都对着 stores/ui 与 ModelDownloadPopover 的真实行为。
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App as AntdApp } from 'antd';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { JobInfo, ServiceEvent } from '@dramaclip/protocol';
import { subscribeModelDownloadProgress, useUiStore } from '../../../stores/ui';
import { activeStateNote } from '../assetState';
import { downloadingLabel } from '../downloadLabel';
import { DownloadSourceButton } from '../ModelDownloadPopover';
import { model, report } from './fixtures';

const download = vi.fn((...args: unknown[]) => Promise.resolve({ job_id: 'j1', args }));
const jobList = vi.fn<
  (limit: number, activeOnly?: boolean) => Promise<{ jobs: JobInfo[]; server_time_ms: number }>
>(() => Promise.resolve({ jobs: [], server_time_ms: 0 }));
const jobCancel = vi.fn(
  (jobId: string): Promise<{ job_id: string; cancelling: boolean; reason?: string }> =>
    Promise.resolve({ job_id: jobId, cancelling: true }),
);
let captured: ((event: ServiceEvent) => void) | null = null;

// vi.mock 会被提升到 import 之前执行，但工厂里的闭包在测试期才被调用——
// 届时 download / captured 都已初始化，这正是「替身只接线、不抢跑」的写法。
vi.mock('../../../services/client', () => ({
  engineConfigsApi: {
    list: vi.fn(() => Promise.resolve({ configs: [] })),
    create: vi.fn(() => Promise.resolve({ id: 'cfg1', domain: '', name: '', base_url: '', api_key: '', model: '', enabled: 0, api_key_masked: '' })),
    update: vi.fn(() => Promise.resolve({})),
    remove: vi.fn(() => Promise.resolve({ ok: true })),
    enable: vi.fn(() => Promise.resolve({})),
    enableLocal: vi.fn(() => Promise.resolve({ ok: true })),
    test: vi.fn(() => Promise.resolve({ ok: true, latency_s: 0.1, error: null })),
  },

  modelsApi: { download: (id: string, source?: string) => download(id, source) },
  jobsApi: {
    list: (limit: number, activeOnly?: boolean) => jobList(limit, activeOnly),
    cancel: (jobId: string) => jobCancel(jobId),
  },
  localRuntimeApi: {
    status: vi.fn(() =>
      Promise.resolve({
        installed: true, dir: '', torch_variant: 'cuda',
        groups: { indextts: true, funasr: true, kokoro: true, torch: true },
      }),
    ),
    install: vi.fn(() => Promise.resolve({ job_id: 'j-local' })),
  },
  onServiceEvent: (cb: (event: ServiceEvent) => void) => {
    captured = cb;
    return () => undefined;
  },
}));

function progressEvent(params: Record<string, unknown>): void {
  const event: ServiceEvent = {
    type: 'notification',
    method: 'models.download_progress',
    params,
  };
  captured?.(event);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  captured = null;
  useUiStore.setState({ modelDownloads: {} });
});

describe('subscribeModelDownloadProgress · 事件原话进 store', () => {
  it('速度/ETA/失败原因照单收下，status 三态如实', () => {
    subscribeModelDownloadProgress();
    progressEvent({
      model_id: 'faster-whisper-small',
      percent: 40.6,
      status: 'downloading',
      speed: '3.2 MB/s',
      eta: '3分20秒',
    });
    expect(useUiStore.getState().modelDownloads['faster-whisper-small']).toEqual({
      percent: 40.6,
      status: 'downloading',
      speed: '3.2 MB/s',
      eta: '3分20秒',
      message: '',
    });

    progressEvent({
      model_id: 'faster-whisper-small',
      percent: 0,
      status: 'failed',
      message: '网络超时或连接被断——稍后重试',
    });
    const state = useUiStore.getState().modelDownloads['faster-whisper-small'];
    expect(state?.status).toBe('failed');
    expect(state?.message).toBe('网络超时或连接被断——稍后重试');
  });

  it('缺字段不瞎猜：没有 speed/eta/message 就是空串，界面上才显示「—」', () => {
    subscribeModelDownloadProgress();
    progressEvent({ model_id: 'kokoro-82m', percent: 1, status: 'downloading' });
    expect(useUiStore.getState().modelDownloads['kokoro-82m']).toEqual({
      percent: 1,
      status: 'downloading',
      speed: '',
      eta: '',
      message: '',
    });
  });
});

describe('downloadingLabel · 进度三件套（§10.6：缺 ETA 显示 —）', () => {
  it('速度 ETA 齐 → 三件套全上', () => {
    expect(
      downloadingLabel({ percent: 45.7, status: 'downloading', speed: '3.2 MB/s', eta: '3分20秒', message: '' }),
    ).toBe('下载中 45% · 3.2 MB/s · 剩 3分20秒');
  });

  it('估不出 ETA → 显示「剩 —」；没速度就不硬凑一段', () => {
    expect(downloadingLabel({ percent: 12, status: 'downloading', speed: '', eta: '', message: '' })).toBe(
      '下载中 12% · 剩 —',
    );
  });
});

describe('DownloadSourceButton · 三态渲染', () => {
  it('下载中 → 禁用按钮带三件套', () => {
    useUiStore
      .getState()
      .setModelDownload('kokoro-82m', { percent: 45, status: 'downloading', speed: '3.2 MB/s', eta: '1分02秒', message: '' });
    render(
      <AntdApp>
        <DownloadSourceButton model={model()} onChanged={() => undefined} />
      </AntdApp>,
    );
    const button = screen.getByRole('button', { name: /下载中 45%/ });
    expect(button.textContent).toBe('下载中 45% · 3.2 MB/s · 剩 1分02秒');
    expect(button.hasAttribute('disabled')).toBe(true);
  });

  it('failed → 「重试」：名字与动作同权重，点了真发下载（附录 B② 的失败态从不可见到可见可修）', () => {
    useUiStore
      .getState()
      .setModelDownload('kokoro-82m', { percent: 30, status: 'failed', speed: '', eta: '', message: '磁盘空间不足：标称 1.5GB，当前盘仅剩 200MB' });
    render(
      <AntdApp>
        <DownloadSourceButton model={model()} onChanged={() => undefined} />
      </AntdApp>,
    );
    fireEvent.click(screen.getByRole('button', { name: /重试/ }));
    expect(download).toHaveBeenCalledWith('kokoro-82m', undefined);
  });

  it('done 之后回到常态下载按钮（完成态不该一直挂着）', () => {
    useUiStore.getState().setModelDownload('kokoro-82m', { percent: 100, status: 'done', speed: '', eta: '', message: '' });
    render(
      <AntdApp>
        <DownloadSourceButton model={model()} onChanged={() => undefined} />
      </AntdApp>,
    );
    expect(screen.getByRole('button', { name: /下载/ })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /重试/ })).toBeNull();
  });
});

describe('下载中的取消入口（规格 H3 §3.1.2）', () => {
  const job = (id: string, refId: string): JobInfo => ({
    id,
    type: 'model_download',
    ref_id: refId,
    status: 'running',
    progress: 45,
    created_at: 0,
    updated_at: 0,
  });

  function downloading(): void {
    useUiStore.getState().setModelDownload('kokoro-82m', {
      percent: 45,
      status: 'downloading',
      speed: '2 MB/s',
      eta: '1分02秒',
      message: '',
    });
    render(
      <AntdApp>
        <DownloadSourceButton model={model()} onChanged={() => undefined} />
      </AntdApp>,
    );
  }

  it('下载中就有「取消」：按 ref_id 认领那一支 model_download，取消成功随即销账', async () => {
    downloading();
    jobList.mockResolvedValueOnce({ jobs: [job('j7', 'other-model'), job('j8', 'kokoro-82m')], server_time_ms: 0 });
    fireEvent.click(screen.getByRole('button', { name: /取\s*消/ }));
    await waitFor(() => {
      expect(jobCancel).toHaveBeenCalledWith('j8');
    });
    expect(useUiStore.getState().modelDownloads['kokoro-82m']).toBeUndefined();
  });

  it('服务端查不到进行中的下载（刷新页面后的过期账）→ 一样销掉，不留着假「下载中」', async () => {
    downloading();
    fireEvent.click(screen.getByRole('button', { name: /取\s*消/ }));
    expect(await screen.findByText(/服务端已经没有进行中的下载任务/)).toBeTruthy();
    expect(jobCancel).not.toHaveBeenCalled();
    expect(useUiStore.getState().modelDownloads['kokoro-82m']).toBeUndefined();
  });

  it('不可中断时如实回：原因进提示，进度账不动（绝不谎报「已取消」）', async () => {
    downloading();
    jobList.mockResolvedValueOnce({ jobs: [job('j8', 'kokoro-82m')], server_time_ms: 0 });
    jobCancel.mockResolvedValueOnce({ job_id: 'j8', cancelling: false, reason: '任务已终态' });
    fireEvent.click(screen.getByRole('button', { name: /取\s*消/ }));
    expect(await screen.findByText(/取消没生效：任务已终态/)).toBeTruthy();
    expect(useUiStore.getState().modelDownloads['kokoro-82m']?.status).toBe('downloading');
  });
});

describe('activeStateNote · 生效卡补充行（§10.5：不替业主下结论）', () => {
  it('体检 fail → 判据原文优先', () => {
    const broken = report({ ok: false, checks: [{ name: '必需文件齐全', status: 'fail', detail: '缺 config.json' }] });
    expect(activeStateNote('incomplete', broken)).toContain('缺 config.json');
  });

  it('待自检 / 未校验 → 给下一步，不写「可用」', () => {
    expect(activeStateNote('untested', report())).toContain('自检');
    expect(activeStateNote('unverified', undefined)).toContain('体检');
  });

  it('ready → 不画蛇添足', () => {
    expect(activeStateNote('ready', report())).toBeUndefined();
  });
});
