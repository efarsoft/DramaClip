/**
 * 引擎短名 ↔ 展示名/音色表的对账。
 *
 * 撤下的引擎（sherpa-onnx melo，2026-09-20）必须从下拉与音色表里一起消失：留在表里，
 * 业主就能选中一个工厂造不出来的引擎，直到导出才听见失败。
 * 同时它得被「原样回显」而不是报错——设置值可能比代码旧，UI 上不认识也要照实说出来。
 */
import { describe, expect, it } from 'vitest';
import {
  TTS_ENGINES,
  isModelFreeEngine,
  ttsEngineLabel,
  voiceOptions,
} from '../ttsVoices';

describe('配音引擎下拉与音色表', () => {
  it('下拉里只有工厂真能创建的引擎：本地 kokoro + 云端 edge', () => {
    expect([...TTS_ENGINES]).toEqual(['kokoro', 'edge']);
  });

  it('撤下的引擎既没有音色可给，也没有编出来的名字', () => {
    expect(voiceOptions('sherpa_melo')).toEqual([]);
    expect(ttsEngineLabel('sherpa_melo')).toBe('sherpa_melo');
  });

  it('对照：在册引擎两样都有（否则上一条是空转通过的）', () => {
    expect(voiceOptions('kokoro').length).toBeGreaterThan(0);
    expect(ttsEngineLabel('kokoro')).toBe('Kokoro 82M');
  });

  it('只有云端引擎免装模型：本地引擎一律有「缺模型」这一态', () => {
    expect(isModelFreeEngine('edge')).toBe(true);
    expect(isModelFreeEngine('kokoro')).toBe(false);
  });
});
