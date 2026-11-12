import { describe, expect, it } from 'vitest';
import type { ComputeReport } from '@dramaclip/protocol';
import { computeLabel, computeSummary } from '../assetState';

const base: ComputeReport = {
  component: 'asr.whisper', requested: 'auto', resolved: 'cuda',
  actual: 'cpu', fallback: true, reason: 'cublas 缺失', device: 'cpu',
};

describe('computeLabel', () => {
  it('回退要带原因', () => {
    expect(computeLabel(base)).toBe('已回退 CPU：cublas 缺失');
  });
  it('显式 GPU 显示实际设备', () => {
    expect(computeLabel({ ...base, requested: 'cuda', resolved: 'cuda', actual: 'cuda',
      fallback: false, reason: '', device: 'cuda:0' })).toBe('本次实际：GPU（cuda:0）');
  });
  it('DirectML 通道如实显示', () => {
    expect(computeLabel({ ...base, resolved: 'dml', actual: 'dml',
      fallback: false, reason: '', device: 'dml' })).toBe('本次实际：GPU（DirectML）');
  });
  it('没有回执不编造', () => {
    expect(computeLabel(undefined)).toBeUndefined();
  });
});

describe('computeSummary', () => {
  const vision: ComputeReport = {
    component: 'vision.llama', requested: 'auto', resolved: 'cuda', actual: 'cuda',
    fallback: false, reason: '', device: 'Quadro M4000',
  };
  it('单条回执沿用原话（不标环节名）', () => {
    expect(computeSummary([{ ...base, actual: 'cuda', fallback: false, reason: '', device: 'cuda' }]))
      .toBe('本次实际：GPU（cuda）');
  });
  it('多条回执给已登记环节标环节名', () => {
    expect(computeSummary([
      { ...base, component: 'asr.funasr', actual: 'cuda', fallback: false, reason: '', device: 'cuda' },
      vision,
    ])).toBe('转写 GPU（cuda） · 画面理解 GPU（Quadro M4000）');
  });
  it('未登记环节的多回执维持原话（导出任务的既有文案不动）', () => {
    expect(computeSummary([
      { ...base, component: 'tts.separation', actual: 'cloud', resolved: 'cloud', fallback: false, reason: '' },
      { ...base, component: 'video.encode', requested: 'cpu', resolved: 'libx264', actual: 'libx264', fallback: false, reason: '' },
    ])).toBe('本次实际：云端 · 编码：libx264');
  });
  it('没证据的回执跳过，一条不剩就是空串', () => {
    expect(computeSummary([])).toBe('');
    expect(computeSummary([{ ...base, actual: 'unknown', fallback: false, reason: '' }])).toBe('');
  });
});
