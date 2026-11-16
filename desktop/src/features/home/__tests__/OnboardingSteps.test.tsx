// @vitest-environment jsdom
/** 首启三步（规格 §4.2）：完成态与动作的正确性。2026-11-16 一键引导批起，ASR 步
 *  的动作是「一键下载推荐模型」（点一下默认源直下），判据放宽为任一 ASR 模型已装
 *  （required 只有 base——照提示装推荐 Small 不打勾是既有错位）。清单未回/无候选
 *  回退「去下载」跳转。 */
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { App as AntdApp } from 'antd';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type { ModelInfo } from '@dramaclip/protocol';
import { OnboardingSteps } from '../OnboardingSteps';
import { useUiStore } from '../../../stores/ui';

const download = vi.hoisted(() => vi.fn());

vi.mock('../../../services/client', () => ({
  localRuntimeApi: {
    status: vi.fn(() =>
      Promise.resolve({
        installed: true, dir: '', torch_variant: 'cuda',
        groups: { indextts: true, funasr: true, kokoro: true, torch: true },
      }),
    ),
    install: vi.fn(() => Promise.resolve({ job_id: 'j' })),
  },
  modelsApi: { download: (modelId: string, source?: string): unknown => download(modelId, source) },
}));

afterEach(() => {
  cleanup();
  download.mockClear();
  useUiStore.setState({ modelDownloads: {} });
});

function asrModel(modelId: string, status: string, required: boolean): ModelInfo {
  return {
    model_id: modelId,
    kind: 'asr',
    engine: 'faster_whisper',
    repo_id: `Systran/${modelId}`,
    name: 'Whisper',
    required,
    status,
    engine_ready: true,
  };
}

function wrapper({ children }: { children: ReactNode }): ReactNode {
  // OneClickDownload/取消件走 AntdApp.useApp() 的 message——必须在 App 上下文里渲染
  return <AntdApp><MemoryRouter>{children}</MemoryRouter></AntdApp>;
}

function renderSteps(models: ModelInfo[] | null, llmBaseUrl = '') {
  const onModelsChanged = vi.fn();
  const view = render(
    <OnboardingSteps models={models} llmBaseUrl={llmBaseUrl} onModelsChanged={onModelsChanged} />,
    { wrapper },
  );
  return { ...view, onModelsChanged };
}

const DOWNLOADING = {
  percent: 42, status: 'downloading' as const, speed: '3.2 MB/s', eta: '1分', message: '',
};

describe('OnboardingSteps', () => {
  it('清单未回（null）：回退去下载跳转，一键按钮不出现', () => {
    renderSteps(null);
    expect(screen.getByText('去下载')).toBeTruthy();
    expect(screen.queryByText('一键下载推荐模型')).toBeNull();
    expect(screen.getByText('去配置')).toBeTruthy();
  });

  it('未装+推荐在场：一键按钮就地可点，不再跳引擎中心', () => {
    renderSteps([asrModel('faster-whisper-small', 'not_installed', false)]);
    expect(screen.getByText('一键下载推荐模型')).toBeTruthy();
    expect(screen.queryByText('去下载')).toBeNull();
  });

  it('点一键：download 以推荐 model_id 发出（默认源序，零选择直下）', async () => {
    download.mockResolvedValue({ job_id: 'j1' });
    renderSteps([asrModel('faster-whisper-small', 'not_installed', false)]);
    screen.getByText('一键下载推荐模型').click();
    await waitFor(() => {
      // 第二参 undefined = 不指定下载源，走服务端默认源序（国内优先）
      expect(download).toHaveBeenCalledWith('faster-whisper-small', undefined);
    });
  });

  it('下载中：行内进度三件套 + 取消入口，一键按钮消失', () => {
    useUiStore.setState({
      modelDownloads: { 'faster-whisper-small': DOWNLOADING },
    });
    renderSteps([asrModel('faster-whisper-small', 'not_installed', false)]);
    expect(screen.getByText(/下载中 42%/)).toBeTruthy();
    expect(screen.getByText('取 消')).toBeTruthy(); // antd 按钮对两字 CJK 自动插空格
    expect(screen.queryByText('一键下载推荐模型')).toBeNull();
  });

  it('完成：重拉回调恰好一次，动作区让空等步骤打勾接管', async () => {
    useUiStore.setState({
      modelDownloads: { 'faster-whisper-small': { ...DOWNLOADING, percent: 100, status: 'done', speed: '', eta: '' } },
    });
    const { onModelsChanged } = renderSteps([asrModel('faster-whisper-small', 'not_installed', false)]);
    await waitFor(() => {
      expect(onModelsChanged).toHaveBeenCalledTimes(1);
    });
    expect(screen.queryByText('一键下载推荐模型')).toBeNull();
  });

  it('失败：原因原文行内可见 + 重试入口（不是只给 toast）', () => {
    useUiStore.setState({
      modelDownloads: { 'faster-whisper-small': { ...DOWNLOADING, status: 'failed', message: '网络中断' } },
    });
    renderSteps([asrModel('faster-whisper-small', 'not_installed', false)]);
    expect(screen.getByText('网络中断')).toBeTruthy();
    expect(screen.getByText('重试')).toBeTruthy();
  });

  it('判据放宽回归钉：非 required 的 ASR 模型已装同样打勾且无动作', () => {
    renderSteps([asrModel('faster-whisper-small', 'installed', false)]);
    expect(screen.queryByText('一键下载推荐模型')).toBeNull();
    expect(screen.queryByText('去下载')).toBeNull();
    expect(screen.queryByText('重试')).toBeNull();
  });
});
