// @vitest-environment node
/**
 * 排版契约门禁·站点层（规格 §2、§3.2）。
 * token 表的形状在 typeContract.test.ts；这里断言的是 mixins 交给组件的**那份 style 对象**：
 * 行高必须能被内容顶开（固定 height 会裁掉折行的解说文案），三态必须各走各的通道。
 */
import { describe, expect, it } from 'vitest';
import { listRow } from '../styles/mixins';
import { layout, tokens } from '../styles/theme';

describe('§2 列表行高统一', () => {
  it('单行档取 36、双行档取 52，且登记进 layout.row', () => {
    expect(listRow().minHeight).toBe(layout.row.single);
    expect(listRow({ rows: 2 }).minHeight).toBe(layout.row.double);
    expect(layout.row).toMatchObject({ single: 36, double: 52 });
  });

  it('纵向不留 padding——留了就顶破固定行高', () => {
    expect(listRow().padding).toBe(`0 ${tokens.spaceMd}`);
  });
});

describe('§3.2 三态分道', () => {
  it('已勾选只铺底，不给竖条', () => {
    const checked = listRow({ checked: true });
    expect(checked.background).toBe(tokens.checkedSoft);
    expect(checked.boxShadow).toBe('none');
  });

  it('当前查看只给竖条，不铺底', () => {
    const active = listRow({ active: true });
    expect(active.boxShadow).toBe(`inset ${String(layout.sectionBar.width)}px 0 0 ${tokens.colorPrimary}`);
    expect(active.background).toBe('transparent');
  });

  it('两态同时在场时两条通道都在（调用方负责别把它们叠给同一行）', () => {
    const both = listRow({ checked: true, active: true });
    expect(both.background).toBe(tokens.checkedSoft);
    expect(both.boxShadow).not.toBe('none');
  });
});
