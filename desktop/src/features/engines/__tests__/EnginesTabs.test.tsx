/**
 * 两段式骨架：卡上每句状态都由传入的 models/reports 折算，不得是组件里写死的常量。
 * 把装好的模型改成未落盘，卡片必须从「就绪」翻成「缺模型」，行内也不给「选为生效」。
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ModelInfo, SelftestResults, VerifyReport } from '@dramaclip/protocol';
import { TtsTab } from '../TtsTab';
import { AsrTab } from '../AsrTab';
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
  ttsApi: {
    preview: vi.fn(() => Promise.resolve({ path: 'C:/x/tts-preview/edge-a.mp3', duration_s: 2.5, engine: 'edge', voice: 'v', text: 't' })),
  },
  mediaUrl: (path: string) => `dramaclip://local/${path}`,
  systemApi: { health: vi.fn(() => Promise.resolve({})) },
  runtimeApi: { status: vi.fn(() => Promise.resolve({ installed: true })), install: vi.fn(() => Promise.resolve({})) },
  revealInFolder: vi.fn(() => Promise.resolve({})),
}));

type Reports = ReadonlyMap<string, VerifyReport>;

const noop = (): void => {
  // 渲染测试只验状态，不验写回
};

function tts(
  models: readonly ModelInfo[],
  reports: Reports,
  engine = 'kokoro',
  selftests?: SelftestResults,
): void {
  const base = {
    imported: [],
    importError: '',
    machine: specsFromHealth(null),
    onSave: noop,
    onChanged: noop,
    onVerify: noop,
    onForget: noop,
    onImport: noop,
  };
  render(
    <TtsTab
      {...base}
      models={[...models]}
      settings={{ 'tts.engine': engine }}
      reports={reports}
      selftests={selftests}
    />,
  );
}

describe('配音 TTS · 自检口径（§10.1：就绪 = 校验过 + 自检过）', () => {
  afterEach(cleanup);

  it('已装 + 校验通过 + 自检通过 → 就绪（两层都过才发绿灯）', () => {
    tts([model()], reportsOf(report()), 'kokoro', { 'kokoro-82m': { ok: true, duration_s: 3.2 } });
    expect(screen.getAllByText('Kokoro 82M 中文').length).toBeGreaterThan(0);
    expect(screen.getAllByText('就绪').length).toBeGreaterThan(0);
    expect(screen.queryByText('缺模型')).toBeNull();
  });

  it('校验通过但没自检 → 待自检：不冒充就绪，但「选为生效」不被禁（自检是就绪口径不是准入闸）', () => {
    tts([model()], reportsOf(report()));
    expect(screen.getAllByText('待自检').length).toBeGreaterThan(0);
    expect(screen.queryByText('就绪')).toBeNull();
    const activate = screen.getByRole('button', { name: '选为生效' });
    expect(activate.hasAttribute('disabled')).toBe(false);
  });
});

describe('配音 TTS · 生效卡与资产库', () => {
  afterEach(cleanup);

  it('模型目录不见了（改名/删除）→ 就绪翻成缺模型，且不给「选为生效」', () => {
    tts([model({ status: 'not_installed', size_bytes: 0 })], reportsOf());
    expect(screen.getAllByText('缺模型').length).toBeGreaterThan(0);
    expect(screen.queryByText('就绪')).toBeNull();
    expect(screen.queryByText('选为生效')).toBeNull();
  });

  it('体检不通过 → 不完整，并把 fail 判据原文带上', () => {
    tts(
      [model()],
      reportsOf(
        report({ ok: false, checks: [{ name: '必需文件齐全', status: 'fail', detail: '缺 config.json' }] }),
      ),
    );
    expect(screen.getAllByText('不完整').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/缺 config\.json/).length).toBeGreaterThan(0);
    const activate = screen.getByRole('button', { name: '选为生效' });
    expect(activate.hasAttribute('disabled')).toBe(true);
  });

  it('引擎未接入的资产只进「储备」分区且默认收起，可用区不出现它', () => {
    tts(
      [model({ model_id: 'indextts2', engine: 'indextts2', name: 'IndexTTS2', engine_ready: false })],
      reportsOf(),
    );
    expect(screen.getByText(/储备 · 待接入（1）/)).toBeTruthy();
    expect(screen.queryByText('IndexTTS2')).toBeNull();
  });

  it('试听挂在生效卡的音色行上；落盘的资产行各带一个，未落盘的不带', () => {
    tts([model()], reportsOf(report()));
    // 卡上 1 个 + 可用区那一行 1 个
    expect(screen.getAllByText('试听')).toHaveLength(2);
  });

  it('卡上说明写破试听的口径：引擎原声，不等于成片响度', () => {
    tts([model()], reportsOf(report()));
    expect(screen.getByText(/引擎原声/)).toBeTruthy();
  });

  it('资产没下载 → 行内不给试听（点了也只会得到一声失败）', () => {
    tts([model({ status: 'not_installed', size_bytes: 0 })], reportsOf());
    expect(screen.getAllByText('试听')).toHaveLength(1);
  });

  it('储备资产（引擎未接入）展开后行内也不给试听', () => {
    tts(
      [model(), model({ model_id: 'indextts2', engine: 'indextts2', name: 'IndexTTS2', engine_ready: false })],
      reportsOf(report()),
    );
    fireEvent.click(screen.getByRole('button', { name: '展开' }));
    expect(screen.getByText('IndexTTS2')).toBeTruthy();
    expect(screen.getAllByText('试听')).toHaveLength(2);
  });
});

describe('语音识别 ASR · 同构骨架', () => {
  afterEach(cleanup);

  it('生效卡 + 资产库两段齐全，档位状态来自资产库（GPU 卡归总览 tab）', () => {
    render(
      <AsrTab
        models={[
          model({
            model_id: 'faster-whisper-small',
            kind: 'asr',
            engine: 'faster_whisper',
            name: 'Whisper Small',
            required: true,
          }),
        ]}
        settings={{ 'asr.engine': 'faster_whisper', 'asr.model': 'small', 'asr.device': 'auto', 'asr.language': 'zh' }}
        reports={reportsOf(report({ model_id: 'faster-whisper-small', kind: 'asr', engine: 'faster_whisper' }))}
        selftests={{ 'faster-whisper-small': { ok: true, chars: 56, elapsed_s: 8.4 } }}
        machine={specsFromHealth(null)}
        onSave={noop}
        onChanged={noop}
        onVerify={noop}
        imported={[]}
        importError=""
        onForget={noop}
        onImport={noop}
      />,
    );
    expect(screen.getByText('当前生效')).toBeTruthy();
    expect(screen.queryByText('转写加速（GPU）')).toBeNull();
    expect(screen.getByText('资产库')).toBeTruthy();
    expect(screen.getAllByText('Whisper Small').length).toBeGreaterThan(0);
    expect(screen.getAllByText('就绪').length).toBeGreaterThan(0);
  });
});
