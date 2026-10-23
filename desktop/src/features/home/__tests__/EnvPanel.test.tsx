// @vitest-environment jsdom
/**
 * 右栏环境行的占位口径（规格 H3 §3.3）：`…` 只准出现在还活着的过程里。
 * 探测被 catch 吞掉后一直挂着「…」，用户读到的是「马上就出」，真相是「答不上来」——
 * 终局无数必须换 `—` 并把原因写进可见文本。
 */
import { App as AntdApp } from 'antd';
import { cleanup, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ModelInfo } from '@dramaclip/protocol';
import { localRuntimeApi } from '../../../services/client';
import { EnvPanel } from '../EnvPanel';

vi.mock('../../../services/client', () => ({
  localRuntimeApi: { status: vi.fn(() => Promise.resolve({ installed: true, dir: '', torch_variant: 'cuda', groups: { funasr: true, kokoro: true } })) },
}));

const ASR_MODEL: ModelInfo = {
  model_id: 'funasr', kind: 'asr', engine: 'funasr', repo_id: 'x/y',
  name: '本地识别', required: true, status: 'installed', size_label: '~1GB', engine_ready: true,
};

function panel(models: ModelInfo[] | null): void {
  render(
    <AntdApp>
      <MemoryRouter>
        <EnvPanel models={models} llmBaseUrl="https://x" ttsEngine="edge" />
      </MemoryRouter>
    </AntdApp>,
  );
}

beforeEach(() => {
  vi.mocked(localRuntimeApi.status).mockResolvedValue({
    installed: true, dir: '', torch_variant: 'cuda', groups: { funasr: true, kokoro: true },
  });
});

afterEach(cleanup);

describe('环境就绪度行', () => {
  it('探测被拒：环境行写「探测失败：原话」，不挂「…」（§3.3）', async () => {
    vi.mocked(localRuntimeApi.status).mockRejectedValue(new Error('sidecar 无响应'));
    panel([ASR_MODEL]);
    expect(await screen.findByText('探测失败：sidecar 无响应')).toBeTruthy();
    expect(screen.queryByText('…')).toBeNull();
  });

  it('目录还在取：识别行留「…」（这才是活着的过程）', () => {
    panel(null);
    const row = screen.getByText('ASR 语音识别').closest('div');
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText('…')).toBeTruthy();
  });

  it('目录取到了却没有必装识别模型：如实 — + 原因', () => {
    panel([]);
    expect(screen.getByText('— · 目录里没有必装识别模型')).toBeTruthy();
  });
});
