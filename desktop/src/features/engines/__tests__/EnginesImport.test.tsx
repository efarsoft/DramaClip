// @vitest-environment jsdom
/**
 * 引擎中心页级真挂载：组件级用例（ExternalAssets.test.tsx）喂着 props 渲染，发现不了
 * 页面忘拉 models.import_records、跨域串登记、向导落位后不刷新这类接线遗漏。
 * 这里验 load() 取数、按域过滤、撤销登记回传与「划完再拉一次」、向导第 ④ 步交回
 * model_id 后页面怎么写设置（查不到这一行就一句也不写）。
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { App as AntdApp } from 'antd';
import { MemoryRouter } from 'react-router-dom';
import { EnginesPage } from '../EnginesPage';
import { externalRecord, importJob, importRecord, inspection, model } from './fixtures';

const asrExternal = externalRecord({ kind: 'asr', label: '同事给的识别模型', path: 'E:\\下载\\同事给的识别模型' });
const ttsExternal = externalRecord({ kind: 'tts', label: '同事给的配音模型', path: 'E:\\下载\\同事给的配音模型' });

const api = vi.hoisted(() => ({
  list: vi.fn(),
  verify: vi.fn(),
  importRecords: vi.fn(),
  forgetImport: vi.fn(),
  inspect: vi.fn(),
  commit: vi.fn(),
  job: vi.fn(),
  pick: vi.fn(),
  rpc: vi.fn(),
}));

vi.mock('../../../services/client', () => ({
  modelsApi: {
    list: api.list,
    verify: api.verify,
    importRecords: api.importRecords,
    forgetImport: api.forgetImport,
    inspectImport: api.inspect,
    commitImport: api.commit,
    remove: vi.fn(() => Promise.resolve({ ok: true })),
    download: vi.fn(() => Promise.resolve({ job_id: 'j' })),
  },
  jobsApi: { get: api.job },
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
  systemApi: { health: vi.fn(() => Promise.resolve({})) },
  mediaUrl: (path: string) => `dramaclip://local/${path}`,
  pickFolder: api.pick,
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

function page(): void {
  render(
    <MemoryRouter initialEntries={['/engines/asr']}>
      <AntdApp>
        <EnginesPage />
      </AntdApp>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  api.list.mockResolvedValue([model({ kind: 'asr', model_id: 'faster-whisper-small', engine: 'faster_whisper' })]);
  api.verify.mockResolvedValue([]);
  api.importRecords.mockResolvedValue({ records: [asrExternal, ttsExternal], error: '' });
  api.forgetImport.mockResolvedValue({ ok: true, path: asrExternal.path });
  api.inspect.mockResolvedValue(inspection());
  api.commit.mockResolvedValue({ job_id: 'j1' });
  api.job.mockResolvedValue({ job: importJob() });
  api.pick.mockResolvedValue(inspection().source_path);
  api.rpc.mockImplementation((method: string) => Promise.resolve(method === 'settings.get' ? {} : { ok: true }));
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('引擎中心页接登记本', () => {
  /** 页面是单页六段，「别域不串台」要按段判：ASR 段只有 ASR 的货，TTS 段只有 TTS 的。 */
  async function sectionOf(id: string): Promise<HTMLElement> {
    return waitFor(() => {
      const el = document.getElementById(id);
      if (el === null) throw new Error(`${id} 段还没渲染`);
      return el;
    });
  }

  it('本域的外部登记进本域段，别域的绝不串台', async () => {
    page();

    const asrSection = await sectionOf('engines-asr');
    expect(within(asrSection).getByText('同事给的识别模型')).toBeTruthy();
    expect(within(asrSection).queryByText('同事给的配音模型')).toBeNull();

    const ttsSection = await sectionOf('engines-tts');
    expect(within(ttsSection).getByText('同事给的配音模型')).toBeTruthy();
    expect(within(ttsSection).queryByText('同事给的识别模型')).toBeNull();
  });

  it('登记本读坏了：原话上屏，不当成库里没货', async () => {
    api.importRecords.mockResolvedValue({ records: [], error: 'imported.json 读不出来：JSON 在第 12 行断了' });
    page();

    // 两个资产库段各挂一条同款横幅：坏登记本是全局事实，页面上不止一处说法也得一致
    const hits = await screen.findAllByText(/imported\.json 读不出来/);
    expect(hits.length).toBeGreaterThan(0);
  });

  it('撤销登记交的是那条路径，交完再拉一次登记本', async () => {
    page();
    // ASR/TTS 两段各有一颗：第一颗在 ASR 段，对应 asrExternal
    const [first] = await screen.findAllByRole('button', { name: '撤销登记' });
    if (first === undefined) throw new Error('页面上找不到「撤销登记」');
    fireEvent.click(first);
    const calls = api.importRecords.mock.calls.length;

    fireEvent.click(await screen.findByRole('button', { name: '确认撤销' }));

    await waitFor(() => {
      expect(api.forgetImport).toHaveBeenCalledWith(asrExternal.path);
    });
    await waitFor(() => {
      expect(api.importRecords.mock.calls.length).toBeGreaterThan(calls);
    });
  });

  it('工具栏那颗按钮在页面上把向导叫起来', async () => {
    page();
    const [first] = await screen.findAllByRole('button', { name: '导入本地模型' });
    if (first === undefined) throw new Error('页面上找不到「导入本地模型」');
    fireEvent.click(first);

    expect(await screen.findByRole('button', { name: '选择目录' })).toBeTruthy();
  });
});

/** 走到第 ④ 步，把弹窗那半边交回来：库里到处是同名按钮，只在弹窗里找。 */
async function toDone(): Promise<HTMLElement> {
  page();
  const [importButton] = await screen.findAllByRole('button', { name: '导入本地模型' });
  if (importButton === undefined) throw new Error('页面上找不到「导入本地模型」');
  fireEvent.click(importButton);
  fireEvent.click(await screen.findByRole('button', { name: '选择目录' }));
  fireEvent.click(await screen.findByRole('button', { name: '下一步' }));
  fireEvent.click(await screen.findByRole('button', { name: '开始导入' }));
  const dialog = await screen.findByRole('dialog');
  await waitFor(() => {
    expect(within(dialog).getByRole('button', { name: '选为生效' })).toBeTruthy();
  });
  return dialog;
}

describe('向导落位后由页面写设置', () => {
  /** 第 ④ 步说「已导入」的同时，资产库就得长出这一行——不等关窗、不等业主自己刷新。 */
  it('落位一结束就刷新资产库，新行立刻看得见', async () => {
    api.list.mockResolvedValueOnce([]);
    api.list.mockResolvedValue([
      model({ model_id: 'faster-whisper-medium', kind: 'asr', engine: 'faster_whisper', name: 'Whisper Medium 刚落位' }),
    ]);
    api.importRecords.mockResolvedValue({ records: [importRecord()], error: '' });
    const dialog = await toDone();

    expect(await screen.findByText('Whisper Medium 刚落位')).toBeTruthy();
    expect(within(dialog).getByText(/已导入/)).toBeTruthy();
  });

  it('库里查得到这一行：向导只交 model_id，写回哪些键由资产库的判据定', async () => {
    api.list.mockResolvedValue([model({ model_id: 'faster-whisper-medium', kind: 'asr', engine: 'faster_whisper' })]);
    api.importRecords.mockResolvedValue({ records: [importRecord()], error: '' });
    const dialog = await toDone();

    fireEvent.click(within(dialog).getByRole('button', { name: '选为生效' }));

    await waitFor(() => {
      expect(api.rpc).toHaveBeenCalledWith('settings.update', {
        values: { 'asr.engine': 'faster_whisper', 'asr.model': 'medium' },
      });
    });
  });

  it('库里查不到这一行：不写设置，把原因说出来', async () => {
    api.list.mockResolvedValue([]);
    api.importRecords.mockResolvedValue({ records: [importRecord()], error: '' });
    const dialog = await toDone();

    fireEvent.click(within(dialog).getByRole('button', { name: '选为生效' }));

    expect(await screen.findByText(/资产库里还没有这一行/)).toBeTruthy();
    expect(api.rpc).not.toHaveBeenCalledWith('settings.update', expect.anything());
  });
});
