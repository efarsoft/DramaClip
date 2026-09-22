// §10.4 锚点深链：/engines/:tab 从「选屏」变「选锚点」。
// 附录 B① 的结案口径：锚点解析必须覆盖 prompts（HEAD 381f32c5 的正则漏过它）。
import { describe, expect, it } from 'vitest';
import { anchorFromPath, SECTION_IDS } from '../engineAnchors';

describe('anchorFromPath', () => {
  it('四个 tab 路径各归各段，prompts 不再回落到总览', () => {
    expect(anchorFromPath('/engines/asr')).toBe(SECTION_IDS.asr);
    expect(anchorFromPath('/engines/tts')).toBe(SECTION_IDS.tts);
    expect(anchorFromPath('/engines/llm')).toBe(SECTION_IDS.llm);
    expect(anchorFromPath('/engines/prompts')).toBe(SECTION_IDS.prompts);
  });

  it('裸 /engines 与认不出的子路径都回落到「就绪与修复」段', () => {
    expect(anchorFromPath('/engines')).toBe(SECTION_IDS.readiness);
    expect(anchorFromPath('/engines/overview')).toBe(SECTION_IDS.readiness);
    expect(anchorFromPath('/engines/nope')).toBe(SECTION_IDS.readiness);
  });

  it('段 id 表覆盖六段：五个深链目标 + 环境段（环境没有历史深链，但表是页面的唯一真相）', () => {
    expect(Object.values(SECTION_IDS)).toHaveLength(6);
    expect(SECTION_IDS.env).toBe('engines-env');
  });
});
