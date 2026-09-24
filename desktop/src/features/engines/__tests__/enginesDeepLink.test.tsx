// @vitest-environment jsdom
/**
 * `/engines/:tab` 深链 = 选 tab（§10.4 修订版）。
 * 附录 B① 的纪律原样继承：解析必须覆盖 prompts，认不出的路径回落总览、不得白屏。
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { App as AntdApp } from 'antd';
import { MemoryRouter } from 'react-router-dom';
import { EnginesPage } from '../EnginesPage';
import { model } from './fixtures';

const api = vi.hoisted(() => ({
  list: vi.fn(),
  verify: vi.fn(),
  importRecords: vi.fn(),
  rpc: vi.fn(),
}));

vi.mock('../../../services/client', () => ({
  modelsApi: {
    list: api.list,
    verify: api.verify,
    importRecords: api.importRecords,
    forgetImport: vi.fn(() => Promise.resolve({ ok: true })),
    inspectImport: vi.fn(),
    commitImport: vi.fn(),
    remove: vi.fn(() => Promise.resolve({ ok: true })),
    download: vi.fn(() => Promise.resolve({ job_id: 'j' })),
  },
  jobsApi: { get: vi.fn() },
  enginesApi: {
    selftest: vi.fn(() => Promise.resolve({ ok: true })),
    selftestResults: vi.fn(() => Promise.resolve({})),
  },
  engineConfigsApi: {
    list: vi.fn(() => Promise.resolve({ configs: [] })),
    create: vi.fn(),
    update: vi.fn(),
    enable: vi.fn(),
    remove: vi.fn(),
    test: vi.fn(),
  },
  promptsApi: {
    list: vi.fn(() => Promise.resolve({ prompts: [] })),
    save: vi.fn(),
    reset: vi.fn(),
  },
  ttsApi: { preview: vi.fn() },
  runtimeApi: { status: vi.fn(() => Promise.resolve({ installed: true })), install: vi.fn() },
  indexttsApi: { status: vi.fn(() => Promise.resolve({ installed: true, dir: '' })), install: vi.fn() },
  systemApi: { health: vi.fn(() => Promise.resolve({})) },
  mediaUrl: (path: string) => `dramaclip://local/${path}`,
  pickFolder: vi.fn(),
  revealInFolder: vi.fn(() => Promise.resolve({})),
  rpc: api.rpc,
}));

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
      // 浮层尺寸由真浏览器观察，这里什么都不必做
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

function page(entry: string): void {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <AntdApp>
        <EnginesPage />
      </AntdApp>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  api.list.mockResolvedValue([model({ kind: 'asr', model_id: 'faster-whisper-small', engine: 'faster_whisper' })]);
  api.verify.mockResolvedValue([]);
  api.importRecords.mockResolvedValue({ records: [], error: '' });
  api.rpc.mockImplementation((method: string) => Promise.resolve(method === 'settings.get' ? {} : { ok: true }));
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('/engines/:tab 深链选 tab', () => {
  it('默认落总览：开工就绪度 + 模型资产都在', async () => {
    page('/engines');

    expect(await screen.findByText('开工就绪度')).toBeTruthy();
    expect(screen.getByText('模型资产')).toBeTruthy();
  });

  it('附录 B①：prompts 深链必须解析到提示词 tab，不得回落总览', async () => {
    page('/engines/prompts');

    expect(await screen.findByText(/这些指令喂给出片链路里的每一次 LLM 调用/)).toBeTruthy();
    expect(screen.queryByText('开工就绪度')).toBeNull();
  });

  it('认不出的路径回落总览，不白屏', async () => {
    page('/engines/nope');

    expect(await screen.findByText('开工就绪度')).toBeTruthy();
  });

  it('左栏点「语音识别 ASR」切到域 tab', async () => {
    page('/engines');
    await screen.findByText('开工就绪度');

    fireEvent.click(screen.getByRole('button', { name: /语音识别 ASR/ }));

    expect(await screen.findByText('资产库')).toBeTruthy();
    expect(screen.queryByText('开工就绪度')).toBeNull();
  });
});
