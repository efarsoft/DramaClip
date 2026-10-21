/** 云端优先档推荐（规划批 A1）：无 NVIDIA 独显时把云端链路推到台前。
 *
 * 只到「建议」为止——不改任何默认引擎，替用户花钱的决定不做主。
 * 事实源全部现成：显卡厂商读 machine.gpu（多卡机任一张 N 卡都算有），
 * 云端启用态读引擎配置表，前端不另设数据通路。
 */
import type { GpuInfo } from '@dramaclip/protocol';

export type CloudRecommendation = 'guide' | 'switch' | 'none';

export function cloudRecommendation(
  gpu: GpuInfo | undefined,
  configs: { readonly enabled: number | boolean }[],
): CloudRecommendation {
  const adapters = gpu?.adapters;
  const hasNvidia = adapters ? adapters.some((a) => a.vendor === 'nvidia') : gpu?.vendor === 'nvidia';
  if (hasNvidia) return 'none';
  if (configs.some((config) => Boolean(config.enabled))) return 'none';
  return configs.length > 0 ? 'switch' : 'guide';
}
