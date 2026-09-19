// machineFit 纯函数：本机规格 + 模型体积 → 可行性结论。
import { describe, expect, it } from 'vitest';
import { judgeMachine, judgeModelFit, parseSizeGb, specsFromHealth } from '../machineFit';

const OK_SPECS = { ramTotalGb: 16, ramFreeGb: 10, diskFreeGb: 100 };

describe('parseSizeGb', () => {
  it('解析 GB 与 MB 标签', () => {
    expect(parseSizeGb('~480MB')).toBeCloseTo(0.469, 2);
    expect(parseSizeGb('~1.5GB')).toBe(1.5);
    expect(parseSizeGb('~9.75GB')).toBe(9.75);
  });

  it('无法解析返回 undefined', () => {
    expect(parseSizeGb(undefined)).toBeUndefined();
    expect(parseSizeGb('未知')).toBeUndefined();
  });
});

describe('judgeModelFit', () => {
  it('规格齐全且余量充足 → ok', () => {
    expect(judgeModelFit(OK_SPECS, 0.5)).toEqual({ verdict: 'ok', reason: '本机可运行' });
  });

  it('磁盘余量不足（体积×1.25 > 可用）→ disk', () => {
    const verdict = judgeModelFit({ ...OK_SPECS, diskFreeGb: 5 }, 4.5);
    expect(verdict.verdict).toBe('disk');
    expect(verdict.reason).toContain('数据盘');
  });

  it('内存需求超总量六成 → ram', () => {
    const verdict = judgeModelFit({ ...OK_SPECS, ramTotalGb: 4, ramFreeGb: 3.9 }, 3);
    expect(verdict.verdict).toBe('ram');
  });

  it('总量够但当前空闲不足 → tight', () => {
    const verdict = judgeModelFit({ ...OK_SPECS, ramFreeGb: 1 }, 1);
    expect(verdict.verdict).toBe('tight');
  });

  it('体积未知或规格缺失 → unknown（不妄下结论）', () => {
    expect(judgeModelFit(OK_SPECS, undefined).verdict).toBe('unknown');
    expect(judgeModelFit({}, 1).verdict).toBe('unknown');
  });
});

describe('judgeMachine / specsFromHealth', () => {
  it('整机按最大模型判定', () => {
    const verdict = judgeMachine(OK_SPECS, 6);
    expect(verdict.verdict).toBe('ok');
    expect(judgeMachine(OK_SPECS, undefined).verdict).toBe('unknown');
  });

  it('从 health 快照提取规格', () => {
    expect(
      specsFromHealth({ status: 'ok', uptime_s: 1, ram_total_gb: 16, disk_free_gb: 88 }),
    ).toEqual({ ramTotalGb: 16, ramFreeGb: undefined, diskFreeGb: 88 });
    expect(specsFromHealth(null)).toEqual({});
  });
});
