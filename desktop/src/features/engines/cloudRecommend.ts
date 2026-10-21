/** 云端优先档推荐（规划批 A1，能力感知版）：本地没有「真能跑的 GPU 通道」时把云端推到台前。
 *
 * 只到「建议」为止——不改任何默认引擎，替用户花钱的决定不做主。
 * 事实源全部现成：显卡厂商读 machine.gpu（多卡机任一张 N 卡都算有），本地加速
 * 是否真就绪读 machine.caps 的 ready（连运行时都装好），云端启用态读引擎配置表。
 * 「有 N 卡」不够格免打扰：GTX10/M4000 这类 sm<7.0 存量卡的 torch 加速跑不了
 * （主流存量段），有卡但通道不就绪时云端建议照样成立。
 */
import type { GpuInfo } from '@dramaclip/protocol';

export type CloudRecommendation = 'guide' | 'switch' | 'none';

export function cloudRecommendation(
  gpu: GpuInfo | undefined,
  configs: { readonly enabled: number | boolean }[],
  localGpuReady: boolean,
): CloudRecommendation {
  if (configs.some((config) => Boolean(config.enabled))) return 'none';
  const adapters = gpu?.adapters;
  const hasNvidia = adapters ? adapters.some((a) => a.vendor === 'nvidia') : gpu?.vendor === 'nvidia';
  if (hasNvidia && localGpuReady) return 'none';
  return configs.length > 0 ? 'switch' : 'guide';
}
