/**
 * §10.4 锚点深链：五 tab 合一后，`/engines/:tab` 的职责从「选屏」变成「选锚点」——
 * 既有 navigate('/engines/<tab>') 调用点（ReadinessCard 的「定位」、home/EnvPanel 的
 * 三条跳转）一行不改，行为变成同页滚动定位。
 * 正则必须覆盖 prompts：附录 B① 的结案口径就是「锚点解析覆盖 prompts」。
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
