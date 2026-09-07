/** 九种出片模式静态信息（展示用；权威定义 service/_MODE_LABELS）。 */

export interface ModeInfoItem {
  readonly mode: string;
  readonly label: string;
  readonly desc: string;
}

export const MODE_INFO: readonly ModeInfoItem[] = [
  { mode: 'raw_clip', label: '纯原片剪辑', desc: 'AI 挑高光直接混剪，无解说，保留原声' },
  { mode: 'intro_narration', label: '片头解说', desc: '前置解说钩子 + 原片正片，开头 3 秒抓人' },
  { mode: 'cross_narration', label: '交叉解说', desc: '解说与原声交替推进，节奏感强' },
  { mode: 'ultra_short_hook', label: '超短悬念版', desc: '30 秒内钩子 + 反转收尾，适配信息流' },
  { mode: 'dialogue_narration', label: '剧情解说', desc: '对白句级筛选，起承转合完整讲一个故事' },
  { mode: 'full_narration', label: '全片解说', desc: '逐段解说全覆盖，信息密度最高' },
  { mode: 'subtitle_flow', label: '字幕金句流', desc: '金句大字卡点 + CTA，无声环境也抓人' },
  { mode: 'dual_host_chat', label: '双人对谈', desc: '双音色对话式解说，像两位博主聊剧' },
  { mode: 'inner_monologue', label: '内心独白', desc: '第一人称 OS 旁白，代入主角视角' },
];
