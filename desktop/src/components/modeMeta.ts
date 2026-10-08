/** 九种出片模式静态信息（展示用；权威定义 service/dramaclip/engines/narration/pipeline.py 的 MODE_LABELS）。 */

export interface ModeInfoItem {
  readonly mode: string;
  readonly label: string;
  readonly desc: string;
  /** 该模式自动生成的内容：文案/配音（纯剪辑类无需）。 */
  readonly needs: ('copy' | 'voice')[];
}

export const MODE_INFO: readonly ModeInfoItem[] = [
  { mode: 'raw_clip', label: '纯原片剪辑', desc: '保留原声台词的高光合集：长度跟剧情走，BGM 关', needs: [] },
  { mode: 'highlight_cut', label: '高光混剪', desc: '5 秒快切 + 情绪配乐的预告片：不给结局只给瘾，BGM 主导', needs: [] },
  { mode: 'intro_narration', label: '片头解说', desc: '最炸场面前置当钩子，正片跟原剧走——像正式预告片', needs: ['copy', 'voice'] },
  { mode: 'cross_narration', label: '交叉解说', desc: '解说串场 + 原声高光交替，节奏感强', needs: ['copy', 'voice'] },
  { mode: 'ultra_short_hook', label: '超短悬念版', desc: '信息流短平快款：开场钩子 + 最高冲突 + 悬念收尾，时长由冲突决定', needs: ['copy', 'voice'] },
  { mode: 'dialogue_narration', label: '剧情解说', desc: '完整讲一个故事的解说正片：起承转合拉完播，主打款', needs: ['copy', 'voice'] },
  { mode: 'full_narration', label: '全片解说', desc: '从头讲到尾的完整覆盖：信息密度最高，适合长视频号', needs: ['copy', 'voice'] },
  { mode: 'subtitle_flow', label: '字幕金句流', desc: '原声台词 + 金句大字卡点：靠剧里最狠的台词说话，静音刷也有字看', needs: [] },
  { mode: 'dual_host_chat', label: '双人对谈', desc: '双音色对话式解说，像两位博主聊剧', needs: ['copy', 'voice'] },
  { mode: 'inner_monologue', label: '内心独白', desc: '第一人称 OS 旁白，代入主角视角', needs: ['copy', 'voice'] },
];

/** 模式 → 中文名；未知模式原样显示（宁可露 id 也不给空白），没有模式时统称「成片」。 */
export function modeLabel(mode: string | undefined): string {
  return MODE_INFO.find((item) => item.mode === mode)?.label ?? mode ?? '成片';
}
