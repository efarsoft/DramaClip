/** IndexTTS 运行环境安装槽的接线回归（2026-09-24 业主实跑抓到的缺口）。
 *
 * 槽组件与钩子一直都在（IndexttsRuntimeSlot/useIndexttsRuntime），却从没被任何页面
 * 挂载——自检与合成失败的文案写着「引擎页『安装运行环境』」，指的是扇不存在的门。
 * 判据：选中 indextts2 且运行环境未装 → 卡内现身一键安装入口；已装 → 消失；
 * 选别的引擎 → 不打扰（2~6GB 的引导对 kokoro 用户毫无意义，连状态都不该查）。
 */
import { App as AntdApp } from 'antd';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { indexttsApi } from '../../../services/client';
import { useUiStore } from '../../../stores/ui';
import { TtsTab } from '../TtsTab';
import { specsFromHealth } from '../machineFit';
import { model, report, reportsOf } from './fixtures';

vi.mock('../../../services/client', () => ({
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
  indexttsApi: {
    status: vi.fn(() => Promise.resolve({ installed: false, dir: '' })),
    install: vi.fn(() => Promise.resolve({ job_id: 'j-install' })),
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

describe('IndexTTS 运行环境安装槽 · 接线', () => {
  afterEach(cleanup);

  beforeEach(() => {
    // 钩子只在服务就绪后查安装态（就绪前查了也是假答案）
    useUiStore.setState({ serviceState: 'ready' });
    vi.mocked(indexttsApi.status).mockResolvedValue({ installed: false, dir: '' });
  });

  it('选中 indextts2 且未装 → 卡内现身「安装运行环境」一键入口', async () => {
    renderTts('indextts2');
    // antd 图标自带 aria-label="download"，可及名是「download 安装运行环境」——用正则
    expect(await screen.findByRole('button', { name: /安装运行环境/ })).toBeTruthy();
    expect(screen.getByText(/IndexTTS 运行环境未安装/)).toBeTruthy();
  });

  it('运行环境已装 → 槽消失，不占地方', async () => {
    vi.mocked(indexttsApi.status).mockResolvedValue({ installed: true, dir: 'C:/rt' });
    renderTts('indextts2');
    await waitFor(() => {
      expect(indexttsApi.status).toHaveBeenCalled();
    });
    expect(screen.queryByRole('button', { name: /安装运行环境/ })).toBeNull();
    expect(screen.queryByText(/IndexTTS 运行环境未安装/)).toBeNull();
  });

  it('选 kokoro → 不打扰：槽不渲染，连安装状态都不查', () => {
    renderTts('kokoro');
    expect(screen.queryByRole('button', { name: /安装运行环境/ })).toBeNull();
    expect(indexttsApi.status).not.toHaveBeenCalled();
  });
});
