import { describe, expect, it } from 'vitest';
import { buildPublishCopy, CHECKLIST_ITEMS } from '../publishCopy';

describe('buildPublishCopy', () => {
  it('选用标题优先，拼接文案/话题/清单', () => {
    const text = buildPublishCopy(
      [{ text: '落选', selected: false }, { text: '当选', selected: true }],
      { caption: '一句文案', tags: ['好剧推荐'] },
    );
    expect(text).toContain('【标题】当选');
    expect(text).toContain('【文案】一句文案');
    expect(text).toContain('#好剧推荐');
    expect(text).toContain('□ 授权覆盖');
    expect(text.split('□').length - 1).toBe(CHECKLIST_ITEMS.length);
  });

  it('无选用取第一条；空物料仍输出清单', () => {
    expect(buildPublishCopy([{ text: '第一条', selected: false }], null)).toContain('【标题】第一条');
    expect(buildPublishCopy([], null).startsWith('【发布前自查】')).toBe(true);
  });

  it('清单五项齐备（报告项⑤）', () => {
    expect(CHECKLIST_ITEMS).toHaveLength(5);
    expect(CHECKLIST_ITEMS.join('|')).toContain('挂载链接');
    expect(CHECKLIST_ITEMS.join('|')).toContain('全程剧名');
  });
});
