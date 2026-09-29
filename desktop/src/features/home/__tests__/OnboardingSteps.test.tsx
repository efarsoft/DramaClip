/** 首启三步（规格 §4.2）：完成态与直达入口的正确性——就绪判定与右栏「环境就绪度」
 *  同源（required ASR 档 + llmBaseUrl），这里钉的是这三步各自的勾选与动作。 */
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ModelInfo } from '@dramaclip/protocol';
import { OnboardingSteps } from '../OnboardingSteps';

afterEach(cleanup);

function asrModel(status: string): ModelInfo {
  return {
    model_id: 'faster-whisper-base',
    kind: 'asr',
    engine: 'faster_whisper',
    repo_id: 'Systran/faster-whisper-base',
    name: 'Whisper Base',
    required: true,
    status,
    engine_ready: true,
  };
}

function renderSteps(models: ModelInfo[] | null, llmBaseUrl: string) {
  const onGo = vi.fn();
  const view = render(
    <MemoryRouter>
      <OnboardingSteps models={models} llmBaseUrl={llmBaseUrl} />
    </MemoryRouter>,
  );
  return { ...view, onGo };
}

describe('OnboardingSteps', () => {
  it('全未就绪：ASR 与 LLM 两步带直达动作，第三步是当前步', () => {
    renderSteps(null, '');
    expect(screen.getByText('去下载')).toBeTruthy();
    expect(screen.getByText('去配置')).toBeTruthy();
    expect(screen.getByText('装一个 ASR 模型')).toBeTruthy();
    expect(screen.getByText('新增项目')).toBeTruthy();
  });

  it('ASR 已装：勾掉且不再给「去下载」', () => {
    renderSteps([asrModel('installed')], '');
    expect(screen.queryByText('去下载')).toBeNull();
  });

  it('ASR 未装（清单在场但 not_installed）：仍要去下载', () => {
    renderSteps([asrModel('not_installed')], '');
    expect(screen.getByText('去下载')).toBeTruthy();
  });

  it('LLM 已配：不再给「去配置」', () => {
    renderSteps(null, 'https://dashscope.example/compatible-mode/v1');
    expect(screen.queryByText('去配置')).toBeNull();
    expect(screen.getByText('去下载')).toBeTruthy();
  });

  it('两步都就绪：只剩第三步（建剧动作在 EmptyWorkbench 的 primary 上）', () => {
    renderSteps([asrModel('installed')], 'https://x.example');
    expect(screen.queryByText('去下载')).toBeNull();
    expect(screen.queryByText('去配置')).toBeNull();
    expect(screen.getByText('新增项目')).toBeTruthy();
  });
});
