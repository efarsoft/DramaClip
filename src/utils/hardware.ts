/**
 * Phase 4 辅助：简单硬件检测（前端侧）
 * 用于 Onboarding 推荐更合适的套装
 */
export async function detectRecommendedPack(): Promise<'light_high_quality' | 'extreme_quality'> {
  try {
    // 尝试通过 WebGPU 或 navigator 粗略判断
    const nav = navigator as any;
    if (nav.gpu) {
      const adapter = await nav.gpu.requestAdapter();
      if (adapter) {
        // 有 WebGPU，通常意味着有较好独显 → 推荐极致套装
        return 'extreme_quality';
      }
    }

    // 回退：如果用户之前装过高配模型或有较多内存，也倾向极致
    if (nav.deviceMemory && nav.deviceMemory >= 16) {
      return 'extreme_quality';
    }
  } catch {}

  return 'light_high_quality';
}
