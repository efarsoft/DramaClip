import { describe, expect, it } from 'vitest';
import type { GpuInfo } from '@dramaclip/protocol';
import { cloudRecommendation } from '../cloudRecommend';

const gpu = (vendor: GpuInfo['vendor'], adapters?: GpuInfo['adapters']): GpuInfo =>
  ({ ready: true, vendor, name: 'x', driver_version: '', max_cuda_version: '', memory_total_mb: 0, compute_cap: '', adapters });

describe('cloudRecommendation', () => {
  it('有 N 卡（含多卡机任一张）不推荐', () => {
    expect(cloudRecommendation(gpu('nvidia'), [])).toBe('none');
    expect(
      cloudRecommendation(gpu('amd', [{ name: 'a', vendor: 'amd', driver_version: '' }, { name: 'b', vendor: 'nvidia', driver_version: '' }]), []),
    ).toBe('none');
  });
  it('无 N 卡：零配置引导、有配置未启用提示切换、已启用不打扰', () => {
    expect(cloudRecommendation(gpu('amd'), [])).toBe('guide');
    expect(cloudRecommendation(gpu('intel'), [{ enabled: 0 }])).toBe('switch');
    expect(cloudRecommendation(gpu('intel'), [{ enabled: 1 }])).toBe('none');
  });
  it('显卡事实缺失按保守处理（未知=无 N 卡，走引导）', () => {
    expect(cloudRecommendation(undefined, [])).toBe('guide');
    expect(cloudRecommendation(gpu('none'), [])).toBe('guide');
  });
});
