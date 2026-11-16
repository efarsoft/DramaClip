/** 一键引导推荐选择的纯函数钉：推荐链（Paraformer-large 三包）与快速档（Whisper Small）
 *  的候选判定——断点自愈（链上已装跳过）、链识别 vs 登记变更回退，两个语义都要钉死。 */
import { describe, expect, it } from 'vitest';
import type { ModelInfo } from '@dramaclip/protocol';
import { nextChainCandidate, pickQuickModel, QUICK_MODEL_ID, RECOMMENDED_CHAIN } from '../onboardingModel';

function asr(modelId: string, status: string): ModelInfo {
  return {
    model_id: modelId,
    kind: 'asr',
    engine: 'funasr',
    repo_id: '',
    name: modelId,
    required: false,
    status,
    engine_ready: true,
  };
}

describe('nextChainCandidate', () => {
  it('链首未装：返回 paraformer-large', () => {
    expect(nextChainCandidate([asr('paraformer-large', 'not_installed')])?.model_id).toBe('paraformer-large');
  });

  it('断点自愈：首包已装跳到下一未装包', () => {
    const models = [
      asr('paraformer-large', 'installed'),
      asr('fsmn-vad', 'installed'),
      asr('campplus-sv', 'not_installed'),
    ];
    expect(nextChainCandidate(models)?.model_id).toBe('campplus-sv');
  });

  it('链全装完：null（无需再装）', () => {
    const models = RECOMMENDED_CHAIN.map((id) => asr(id, 'installed'));
    expect(nextChainCandidate(models)).toBeNull();
  });

  it('链上 id 清单里一个都不在（登记变更）：回退第一个未装 ASR 模型', () => {
    const models = [asr('faster-whisper-small', 'not_installed')];
    expect(nextChainCandidate(models)?.model_id).toBe('faster-whisper-small');
  });

  it('清单未回（null）：null（宿主回退跳转）', () => {
    expect(nextChainCandidate(null)).toBeNull();
  });

  it('全部装完（含链外 ASR）：null', () => {
    const models = [...RECOMMENDED_CHAIN.map((id) => asr(id, 'installed')), asr('faster-whisper-small', 'installed')];
    expect(nextChainCandidate(models)).toBeNull();
  });
});

describe('pickQuickModel', () => {
  it('Whisper Small 未装：返回它', () => {
    expect(pickQuickModel([asr(QUICK_MODEL_ID, 'not_installed')])?.model_id).toBe(QUICK_MODEL_ID);
  });

  it('已装或缺席：null', () => {
    expect(pickQuickModel([asr(QUICK_MODEL_ID, 'installed')])).toBeNull();
    expect(pickQuickModel([asr('paraformer-large', 'not_installed')])).toBeNull();
    expect(pickQuickModel(null)).toBeNull();
  });
});
