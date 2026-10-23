// @vitest-environment jsdom
/** 本地智能运行环境安装槽的接线回归（2026-09-24 业主实跑缺口 + E2-5 分组判缺）。
 *
 * 槽组件换形（IndexttsRuntimeSlot → LocalRuntimeSlot）不改判据：运行环境未装 →
 * 页面无条件现身一键安装入口，不押在「先切到对应引擎」上；已装且本页依赖组齐 →
 * 消失，不做常驻横幅。ASR 页同槽同判据（scope=asr 判 funasr 组，升级补装路径）。
 */
import { App as AntdApp } from 'antd';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { JobInfo } from '@dramaclip/protocol';
import { jobsApi, localRuntimeApi } from '../../../services/client';
import { useUiStore } from '../../../stores/ui';
import { AsrTab } from '../AsrTab';
import { TtsTab } from '../TtsTab';
import { specsFromHealth } from '../machineFit';
import { model, report, reportsOf } from './fixtures';

const jobInfo = (over: Partial<JobInfo>): JobInfo => ({
  id: 'j-local',
  type: 'local_runtime_install',
  ref_id: null,
  status: 'running',
  progress: 0,
  created_at: 0,
  updated_at: 0,
  ...over,
});

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
  modelsApi: {
    list: vi.fn(() => Promise.resolve([])),
    verify: vi.fn(() => Promise.resolve([])),
    remove: vi.fn(() => Promise.resolve({})),
    download: vi.fn(() => Promise.resolve({})),
    cleanResidue: vi.fn(() => Promise.resolve({ removed: 0, freed_bytes: 0 })),
    orphanList: vi.fn(() => Promise.resolve([])),
    cleanOrphan: vi.fn(() => Promise.resolve({ ok: true, removed: '', freed_bytes: 0 })),
    relayout: vi.fn(() => Promise.resolve({ path: '', migrated: false })),
  },
  enginesApi: {
    selftest: vi.fn(() => Promise.resolve({ ok: true })),
    selftestResults: vi.fn(() => Promise.resolve({})),
  },
  ttsApi: { preview: vi.fn(() => Promise.resolve({})) },
  localRuntimeApi: {
    status: vi.fn(() =>
      Promise.resolve({ installed: false, dir: '', torch_variant: 'unknown', groups: {} }),
    ),
    install: vi.fn(() => Promise.resolve({ job_id: 'j-local' })),
  },
  jobsApi: {
    get: vi.fn(() =>
      Promise.resolve({ job: { id: 'j', progress: 0, label: '', status: 'running' } }),
    ),
  },
  mediaUrl: (path: string) => `dramaclip://local/${path}`,
  systemApi: { health: vi.fn(() => Promise.resolve({})) },
  runtimeApi: {
    status: vi.fn(() => Promise.resolve({ installed: true })),
    install: vi.fn(() => Promise.resolve({})),
  },
  revealInFolder: vi.fn(() => Promise.resolve({})),
  pickAudioFile: vi.fn(() => Promise.resolve(null)),
}));

const noop = (): void => {
  // 接线测试只看槽的显隐，不验写回
};

function renderTts(engine: string): void {
  render(
    <AntdApp>
      <TtsTab
        models={[model({ model_id: 'indextts2', engine: 'indextts2', name: 'IndexTTS-2.5' })]}
        imported={[]}
        importError=""
        machine={specsFromHealth(null)}
        settings={{ 'tts.engine': engine }}
        reports={reportsOf(report())}
        onSave={noop}
        onChanged={noop}
        onVerify={noop}
        onForget={noop}
        onImport={noop}
      />
    </AntdApp>,
  );
}

function renderAsr(): void {
  render(
    <AntdApp>
      <AsrTab
        models={[]}
        imported={[]}
        importError=""
        machine={specsFromHealth(null)}
        settings={{}}
        reports={reportsOf(report())}
        onSave={noop}
        onChanged={noop}
        onVerify={noop}
        onForget={noop}
        onImport={noop}
      />
    </AntdApp>,
  );
}

describe('本地智能运行环境安装槽 · 接线', () => {
  afterEach(cleanup);

  beforeEach(() => {
    // 钩子只在服务就绪后查安装态（就绪前查了也是假答案）
    useUiStore.setState({ serviceState: 'ready' });
    vi.mocked(localRuntimeApi.status).mockResolvedValue({
      installed: false, dir: '', torch_variant: 'unknown', groups: {},
    });
  });

  it('未装 + 选 indextts2 → 卡下现身「安装运行环境」一键入口', async () => {
    renderTts('indextts2');
    // antd 图标自带 aria-label="download"，可及名是「download 安装运行环境」——用正则
    expect(await screen.findByRole('button', { name: /安装运行环境/ })).toBeTruthy();
    expect(screen.getByText(/本地智能运行环境未安装/)).toBeTruthy();
  });

  it('已装且各依赖组齐 → 槽消失，不做常驻横幅', async () => {
    vi.mocked(localRuntimeApi.status).mockResolvedValue({
      installed: true, dir: 'C:/rt', torch_variant: 'cuda',
      groups: { indextts: true, funasr: true, kokoro: true, torch: true },
    });
    renderTts('indextts2');
    await waitFor(() => {
      expect(localRuntimeApi.status).toHaveBeenCalled();
    });
    expect(screen.queryByRole('button', { name: /安装运行环境/ })).toBeNull();
    expect(screen.queryByText(/本地智能运行环境/)).toBeNull();
  });

  it('未装 + 选 kokoro → 照样显示（固定显示：入口可见性不押在引擎切换上）', async () => {
    renderTts('kokoro');
    expect(await screen.findByRole('button', { name: /安装运行环境/ })).toBeTruthy();
    expect(localRuntimeApi.status).toHaveBeenCalled();
  });

  it('ASR 页：已装双栈但缺 funasr 组 → 「待更新」补装入口（升级补装路径）', async () => {
    vi.mocked(localRuntimeApi.status).mockResolvedValue({
      installed: true, dir: 'C:/rt', torch_variant: 'cpu',
      groups: { indextts: true, funasr: false, kokoro: true, torch: true },
    });
    renderAsr();
    expect(await screen.findByText(/待更新/)).toBeTruthy();
    expect(await screen.findByRole('button', { name: /安装运行环境/ })).toBeTruthy();
  });

  it('探测取不到 → 槽位说「状态未知」并重探，不报「未安装」、不挂安装按钮（规格 H3 §3.2.1）', async () => {
    vi.mocked(localRuntimeApi.status).mockRejectedValue(new Error('sidecar 无响应'));
    renderTts('indextts2');
    // 同一个未知在配音页有两处读者（安装槽 + 人声分离后端那一行）：一处说未知、另一处静默吞掉就是假账
    const lines = await screen.findAllByText(/状态未知：探测失败（sidecar 无响应）/);
    expect(lines).toHaveLength(2);
    expect(screen.getByRole('button', { name: /重试探测/ })).toBeTruthy();
    expect(screen.queryAllByText(/未安装/)).toHaveLength(0);
    expect(screen.queryByRole('button', { name: /安装运行环境/ })).toBeNull();
  });

  it('安装启动被拒 → 原因常驻槽位并改口径为「重试安装」，不靠一次 toast 交代（规格 H3 §3.1.3）', async () => {
    vi.mocked(localRuntimeApi.install).mockRejectedValueOnce(new Error('磁盘只剩 200MB，装不下 2GB'));
    renderTts('indextts2');
    fireEvent.click(await screen.findByRole('button', { name: /安装运行环境/ }));
    expect(await screen.findByText(/启动安装失败：磁盘只剩 200MB，装不下 2GB/)).toBeTruthy();
    expect(screen.getByRole('button', { name: /重试安装/ })).toBeTruthy();
  });

  it('安装作业失败 → 槽位不消失，原话常驻并给「重试安装」（规格 H3 §3.1.3）', async () => {
    vi.mocked(jobsApi.get).mockResolvedValueOnce({
      job: jobInfo({ status: 'failed', error: 'venv 创建失败：目录只读' }),
    });
    renderTts('indextts2');
    fireEvent.click(await screen.findByRole('button', { name: /安装运行环境/ }));
    // 3s 一轮的作业轮询：这一条花的是真时间，换假定时器会把 antd 的动效一起冻住
    expect(await screen.findByText(/安装失败：venv 创建失败：目录只读/, {}, { timeout: 8000 })).toBeTruthy();
    expect(screen.getByRole('button', { name: /重试安装/ })).toBeTruthy();
  }, 12000);
});
