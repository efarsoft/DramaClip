import { describe, expect, it } from 'vitest';
import type { ComputeReport } from '@dramaclip/protocol';
import { computeLabel } from '../assetState';

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
