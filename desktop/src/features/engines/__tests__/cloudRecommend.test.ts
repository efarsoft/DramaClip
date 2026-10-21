import { describe, expect, it } from 'vitest';
import type { GpuInfo } from '@dramaclip/protocol';
import { cloudRecommendation } from '../cloudRecommend';

const gpu = (vendor: GpuInfo['vendor'], adapters?: GpuInfo['adapters']): GpuInfo =>
  ({ ready: true, vendor, name: 'x', driver_version: '', max_cuda_version: '', memory_total_mb: 0, compute_cap: '', adapters });

describe('cloudRecommendation', () => {
  it('有 N 卡且本地加速真就绪才不打扰（含多卡机任一张）', () => {
    expect(cloudRecommendation(gpu('nvidia'), [], true)).toBe('none');
    expect(
      cloudRecommendation(
        gpu('amd', [{ name: 'a', vendor: 'amd', driver_version: '' }, { name: 'b', vendor: 'nvidia', driver_version: '' }]),
        [],
        true,
      ),
    ).toBe('none');
  });
  it('有 N 卡但通道不就绪照样建议：GTX10/M4000 的 torch 加速跑不了（主流存量段）', () => {
    expect(cloudRecommendation(gpu('nvidia'), [], false)).toBe('guide');
    expect(
      cloudRecommendation(
        gpu('nvidia'),
        [{ enabled: 0 }],
        false,
      ),
    ).toBe('switch');
  });
  it('无 N 卡：零配置引导、有配置未启用提示切换、已启用不打扰', () => {
    expect(cloudRecommendation(gpu('amd'), [], false)).toBe('guide');
    expect(cloudRecommendation(gpu('intel'), [{ enabled: 0 }], false)).toBe('switch');
    expect(cloudRecommendation(gpu('intel'), [{ enabled: 1 }], false)).toBe('none');
  });
  it('显卡事实缺失按保守处理（未知=无就绪通道，走引导）', () => {
    expect(cloudRecommendation(undefined, [], false)).toBe('guide');
    expect(cloudRecommendation(gpu('none'), [], false)).toBe('guide');
  });
});
