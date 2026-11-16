/** 一键引导的推荐选择：纯函数，不发 RPC（测试直 import）。
 *
 * 推荐档（业主拍板 2026-11-16）= Paraformer-large + 配套两件，串装三包：
 *   paraformer-large（880MB，中文最准）+ fsmn-vad（转写硬依赖：无 vad 无输入窗）
 *   + campplus-sv（说话人分离，0.2.5 主打功能默认线不带就是半残）。
 * 跑在 funasr worker（tts-venv）里，一键链要先装本地运行环境。
 * 快速档 = Whisper Small（480MB，主包内跑免装环境），留给只想最快出片的用户。
 */
import type { ModelInfo } from '@dramaclip/protocol';

export const RECOMMENDED_CHAIN: readonly string[] = ['paraformer-large', 'fsmn-vad', 'campplus-sv'];
export const QUICK_MODEL_ID = 'faster-whisper-small';

/** 推荐链上第一个未装的模型；链全装完 → null（无需再装）。
 * 链上 id 在清单里一个都找不到（登记变更）→ 回退第一个未装的 ASR 模型；
 * 连它也没有 → null。 */
export function nextChainCandidate(models: readonly ModelInfo[] | null): ModelInfo | null {
  const byId = new Map((models ?? []).filter((m) => m.kind === 'asr').map((m) => [m.model_id, m]));
  for (const id of RECOMMENDED_CHAIN) {
    const model = byId.get(id);
    if (model !== undefined && model.status !== 'installed') return model;
  }
  if (RECOMMENDED_CHAIN.some((id) => byId.has(id))) return null; // 链识别到了且全装完
  const fallback = (models ?? []).find((m) => m.kind === 'asr' && m.status !== 'installed');
  return fallback ?? null;
}

/** 快速档候选：Whisper Small 未装 → 它；否则 null（已装即无需入口）。 */
export function pickQuickModel(models: readonly ModelInfo[] | null): ModelInfo | null {
  const model = (models ?? []).find((m) => m.model_id === QUICK_MODEL_ID);
  if (model !== undefined && model.status !== 'installed') return model;
  return null;
}
