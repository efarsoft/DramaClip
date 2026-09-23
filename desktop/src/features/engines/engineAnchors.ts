/**
 * §10.4 锚点深链：`/engines/:tab` 指锚点不指屏——既有 navigate 调用点不改，行为是同页滚动定位。
 * 正则必须覆盖 prompts（附录 B① 结案口径：锚点解析覆盖 prompts）。
 */
export const SECTION_IDS = {
  readiness: 'engines-readiness',
  asr: 'engines-asr',
  tts: 'engines-tts',
  llm: 'engines-llm',
  prompts: 'engines-prompts',
  env: 'engines-env',
} as const;

/** 路径 → 段 id：认得的 tab 给对应段，其余（含 /engines 与认不出的）回落到就绪段。 */
export function anchorFromPath(pathname: string): string {
  const matched = /\/engines\/(asr|tts|llm|prompts)/.exec(pathname)?.[1];
  if (matched === 'asr' || matched === 'tts' || matched === 'llm' || matched === 'prompts') {
    return SECTION_IDS[matched];
  }
  return SECTION_IDS.readiness;
}
