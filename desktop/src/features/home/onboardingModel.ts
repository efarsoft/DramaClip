/** 一键引导的推荐模型选择：纯函数，不发 RPC（测试直import）。
 *
 * 推荐默认档 = balanced 档 Whisper Small——主包内跑（免装本地运行环境）、
 * 全机型可用（无卡机器走 CPU 慢档但能用）、国内 ModelScope 优先源。
 * 候选缺席（登记变更/改名）时回退第一个未装的 ASR 模型，不硬编码卡死。
 */
import type { ModelInfo } from '@dramaclip/protocol';

export const RECOMMENDED_MODEL_ID = 'faster-whisper-small';

/** 返回 null = 没有一键候选（清单未回来或 ASR 全部已装），宿主回退跳转引擎中心。 */
export function pickRecommendedModel(models: readonly ModelInfo[] | null): ModelInfo | null {
  const candidates = (models ?? []).filter((m) => m.kind === 'asr' && m.status !== 'installed');
  const preferred = candidates.find((m) => m.model_id === RECOMMENDED_MODEL_ID);
  if (preferred !== undefined) return preferred;
  return candidates[0] ?? null;
}
