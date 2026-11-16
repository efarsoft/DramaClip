// @vitest-environment jsdom
/** 首启三步（规格 §4.2）：完成态与动作的正确性。2026-11-16 双入口批起，ASR 步是
 *  「一键装齐推荐档（Paraformer-large 串装链）+ 快速档（Whisper Small 单包）」——
 *  链状态机自身的行为在 useOnboardingChain.test 钉，这里钉组件静态面与发起转发。 */
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { App as AntdApp } from 'antd';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type { ModelInfo } from '@dramaclip/protocol';
import { OnboardingSteps } from '../OnboardingSteps';

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
  jobsApi: { get: vi.fn(), list: vi.fn(() => Promise.resolve({ jobs: [] })), cancel: vi.fn() },
  modelsApi: {
    download: (modelId: string, source?: string): unknown => download(modelId, source),
    list: vi.fn(() => Promise.resolve([])),
  },
}));

afterEach(() => {
  cleanup();
  download.mockClear();
});

function model(modelId: string, status: string): ModelInfo {
  return {
    model_id: modelId,
    kind: 'asr',
    engine: 'funasr',
    repo_id: '',
    name: modelId,
    required: false,
    status,
    engine_ready: true,
  };
}

function wrapper({ children }: { children: ReactNode }): ReactNode {
  // 动作区走 AntdApp.useApp() 的 message——必须在 App 上下文里渲染
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

const FULL_UNINSTALLED = ['paraformer-large', 'fsmn-vad', 'campplus-sv', 'faster-whisper-small'].map((id) =>
  model(id, 'not_installed'),
);

describe('OnboardingSteps', () => {
  it('清单未回（null）：回退去下载跳转，双入口不出现', () => {
    renderSteps(null);
    expect(screen.getByText('去下载')).toBeTruthy();
    expect(screen.queryByText(/一键装齐推荐档/)).toBeNull();
    expect(screen.queryByText(/快速档：Whisper Small/)).toBeNull();
    expect(screen.getByText('去配置')).toBeTruthy();
  });

  it('推荐链+快速档都未装：双入口就地可点，不再跳引擎中心', () => {
    renderSteps(FULL_UNINSTALLED);
    expect(screen.getByText('一键装齐推荐档（约 910MB + 运行环境）')).toBeTruthy();
    expect(screen.getByText('快速档：Whisper Small（约 480MB，免装运行环境）')).toBeTruthy();
    expect(screen.queryByText('去下载')).toBeNull();
  });

  it('点推荐档：串装链以链首包 paraformer-large 发起下载（默认源序）', async () => {
    download.mockResolvedValue({ job_id: 'd1' });
    renderSteps(FULL_UNINSTALLED);
    screen.getByText('一键装齐推荐档（约 910MB + 运行环境）').click();
    await waitFor(() => {
      expect(download).toHaveBeenCalledWith('paraformer-large', undefined);
    });
  });

  it('推荐链全装完：这步已完成——打勾且不再给任何入口（含快速档）', () => {
    // 链三包装齐 = 「装一个 ASR 模型」完成；快速档是给没装的人的入口，不再出现
    const models = ['paraformer-large', 'fsmn-vad', 'campplus-sv'].map((id) => model(id, 'installed'));
    models.push(model('faster-whisper-small', 'not_installed'));
    renderSteps(models);
    expect(screen.queryByText(/一键装齐推荐档/)).toBeNull();
    expect(screen.queryByText(/快速档：Whisper Small/)).toBeNull();
    expect(screen.queryByText('去下载')).toBeNull();
  });

  it('判据回归钉：任一 ASR 模型已装（非 required）即打勾且无任何动作', () => {
    renderSteps([model('faster-whisper-small', 'installed')]);
    expect(screen.queryByText(/一键装齐推荐档/)).toBeNull();
    expect(screen.queryByText(/快速档：Whisper Small/)).toBeNull();
    expect(screen.queryByText('去下载')).toBeNull();
  });

  it('LLM 已配：不再给「去配置」', () => {
    renderSteps(null, 'https://dashscope.example/compatible-mode/v1');
    expect(screen.queryByText('去配置')).toBeNull();
    expect(screen.getByText('去下载')).toBeTruthy();
  });
});
