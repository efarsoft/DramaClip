// 开工就绪度：四格绿/红一律由设置值 + 资产状态（校验+自检两层）+ 真实探测到的渲染版本折算，
// 前端不得写死任何「免装 / 已就绪」。
import { describe, expect, it } from 'vitest';
import { workReadiness } from '../workReadiness';
import { model, report, reportsOf, selftestOk, selftestsOf } from './fixtures';

const asr = model({
  model_id: 'faster-whisper-small',
  kind: 'asr',
  engine: 'faster_whisper',
  name: 'Whisper Small',
  required: true,
});

const READY = reportsOf(report({ model_id: 'faster-whisper-small', kind: 'asr' }));
const TESTED = selftestsOf(['faster-whisper-small', selftestOk()]);

describe('workReadiness · 全绿', () => {
  it('四个环节全绿 → 可开工', () => {
    const steps = workReadiness({
      models: [asr],
      reports: READY,
      selftests: TESTED,
      settings: { 'asr.model': 'small', 'tts.engine': 'edge', 'llm.base_url': 'https://x/v1' },
      ffmpegVersion: '8.1.1',
    });
    expect(steps.map((s) => s.ok)).toEqual([true, true, true, true]);
    expect(steps[3]?.detail).toBe('ffmpeg 8.1.1');
  });

  it('校验过了但没自检 → 转写格红「待自检」（§10.1 缺陷 4：不给未证实的发绿灯）', () => {
    const steps = workReadiness({
      models: [asr],
      reports: READY,
      settings: { 'asr.model': 'small', 'tts.engine': 'edge', 'llm.base_url': 'https://x/v1' },
      ffmpegVersion: '8.1.1',
    });
    expect(steps[0]?.ok).toBe(false);
    expect(steps[0]?.detail).toBe('Whisper Small · 待自检');
  });
});

describe('workReadiness · 转写环节', () => {
  it('ASR 选的模型没落盘 → 该环节红，且说清缺哪个', () => {
    const steps = workReadiness({
      models: [
        model({
          model_id: 'faster-whisper-small',
          kind: 'asr',
          engine: 'faster_whisper',
          status: 'not_installed',
          size_bytes: 0,
        }),
      ],
      reports: reportsOf(),
      settings: { 'asr.model': 'small' },
      ffmpegVersion: '8.1.1',
    });
    expect(steps[0]?.ok).toBe(false);
    expect(steps[0]?.detail).toContain('缺模型');
  });

  it('ASR 换了引擎（sensevoice）时按 asr.engine 找资产，不再盯死 whisper 档位', () => {
    const sense = model({
      model_id: 'sensevoice-small',
      kind: 'asr',
      engine: 'sensevoice',
      name: 'SenseVoice Small',
    });
    const steps = workReadiness({
      models: [sense],
      reports: reportsOf(report({ model_id: 'sensevoice-small', kind: 'asr', engine: 'sensevoice' })),
      selftests: selftestsOf(['sensevoice-small', selftestOk({ chars: 42 })]),
      settings: { 'asr.engine': 'sensevoice', 'asr.model': 'small' },
      ffmpegVersion: '8.1.1',
    });
    expect(steps[0]?.ok).toBe(true);
    expect(steps[0]?.detail).toBe('SenseVoice Small · 就绪');
  });
});

describe('workReadiness · 配音环节', () => {
  it('云端 Edge 免装即绿；本地 Kokoro 缺模型则红', () => {
    const edge = workReadiness({
      models: [],
      reports: reportsOf(),
      settings: { 'tts.engine': 'edge' },
      ffmpegVersion: '8.1.1',
    });
    expect(edge[2]?.ok).toBe(true);
    expect(edge[2]?.detail).toBe('Edge · 免装');
    const kokoro = workReadiness({
      models: [model({ status: 'not_installed', size_bytes: 0 })],
      reports: reportsOf(),
      settings: { 'tts.engine': 'kokoro' },
      ffmpegVersion: '8.1.1',
    });
    expect(kokoro[2]?.ok).toBe(false);
    expect(kokoro[2]?.detail).toBe('Kokoro 82M 中文 · 缺模型');
  });

  it('未选引擎（设置值为空）不得算绿——「免装」只认后端登记的免模型引擎', () => {
    const steps = workReadiness({
      models: [],
      reports: reportsOf(),
      settings: { 'tts.engine': '' },
      ffmpegVersion: '8.1.1',
    });
    expect(steps[2]?.ok).toBe(false);
    expect(steps[2]?.detail).toBe('未选引擎');
  });

  it('配音引擎虽登记但未接入工厂 → 就绪度报待接入，不算可开工', () => {
    const steps = workReadiness({
      models: [model({ model_id: 'indextts2', engine: 'indextts2', engine_ready: false })],
      reports: reportsOf(),
      settings: { 'tts.engine': 'indextts2' },
      ffmpegVersion: '8.1.1',
    });
    expect(steps[2]?.ok).toBe(false);
    expect(steps[2]?.detail).toContain('待接入');
  });
});

describe('workReadiness · 文案与渲染环节', () => {
  it('LLM 未配置只红文案那一格，且指向 llm tab', () => {
    const steps = workReadiness({
      models: [asr],
      reports: READY,
      selftests: TESTED,
      settings: { 'asr.model': 'small', 'tts.engine': 'edge' },
      ffmpegVersion: '8.1.1',
    });
    expect(steps.map((s) => s.ok)).toEqual([true, false, true, true]);
    expect(steps[1]?.tab).toBe('llm');
    expect(steps[1]?.detail).toBe('未配置 · 解说模式不可用');
  });

  it('渲染环节只看真探测到的版本，空串即红', () => {
    const steps = workReadiness({
      models: [asr],
      reports: READY,
      selftests: TESTED,
      settings: { 'asr.model': 'small', 'llm.base_url': 'https://x/v1' },
      ffmpegVersion: '',
    });
    expect(steps[3]?.ok).toBe(false);
    expect(steps[3]?.detail).toContain('不可用');
  });
});
