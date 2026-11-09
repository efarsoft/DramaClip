/** 发布前自查清单 + 发布包一键复制文本（纯函数）。
 *  清单是动作提醒不是存证数据——不落库（授权存证否决裁决 2026-09-10）。 */
import type { PublishMeta, TitleCandidate } from '@dramaclip/protocol';

export const CHECKLIST_ITEMS = [
  '授权覆盖：确认本剧推广授权覆盖目标平台与切片用途',
  '挂载链接：确认挂载组件/小程序链接已配置且指向正确剧集',
  '标题封面相符：封面帧与标题卖的是同一亮点，不做点击错位',
  '全程剧名：已开「剧名常驻层」开关，或标题/文案含剧名',
  '话题组：含实测高频话题（#好剧推荐 #因为一个片段看了整部剧）',
] as const;

export function buildPublishCopy(titles: TitleCandidate[], publish: PublishMeta | null): string {
  const selected = titles.find((t) => t.selected)?.text ?? titles[0]?.text ?? '';
  const caption = publish?.caption ?? '';
  const tags = publish?.tags.length ? publish.tags.map((t) => `#${t}`).join(' ') : '';
  const parts = [
    selected !== '' ? `【标题】${selected}` : '',
    caption !== '' ? `【文案】${caption}` : '',
    tags !== '' ? `【话题】${tags}` : '',
    `【发布前自查】\n${CHECKLIST_ITEMS.map((item) => `□ ${item}`).join('\n')}`,
  ];
  return parts.filter((part) => part !== '').join('\n');
}
