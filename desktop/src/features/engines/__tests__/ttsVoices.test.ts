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
  it('下拉里只有工厂真能创建的引擎：kokoro + indextts2 本地，edge 云端', () => {
    expect([...TTS_ENGINES]).toEqual(['kokoro', 'edge', 'indextts2', 'cosyvoice_cloud']);
  });

  it('indextts2 音色=参考音频不走下拉，标签如实', () => {
    expect(voiceOptions('indextts2')).toEqual([]);
    expect(ttsEngineLabel('indextts2')).toBe('IndexTTS-2.5');
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

  it('cosyvoice 云端音色表对齐官方列表：性别分组修正、下架音色移除', () => {
    const options = voiceOptions('cosyvoice_cloud');
    expect(options.length).toBeGreaterThan(0);
    const labelOf = new Map(options.map((o) => [o.value as string, o.label as string]));
    // 官方音色列表核对（help.aliyun.com/zh/model-studio/cosyvoice-voice-list）：
    // longhua_v2 / longqiang_v2 是女声、longshu_v2 是男声——错组会把业主引向错误音色
    expect(labelOf.get('longhua_v2')).toContain('女声');
    expect(labelOf.get('longqiang_v2')).toContain('女声');
    expect(labelOf.get('longshu_v2')).toContain('男声');
    expect(labelOf.get('longlaotie_v2')).toContain('男声');
    // longxiang_v2 已不在官方列表——留在表里就是一条合不成的路
    expect(labelOf.has('longxiang_v2')).toBe(false);
  });
});
