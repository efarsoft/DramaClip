// @vitest-environment node
/**
 * 排版契约门禁（规格 docs/superpowers/specs/2026-09-21-desktop-typography-density-design.md §1、§2）。
 * 这里断言的是 token 层的形状与取值：字阶必须成对（字号与行高同一个 token），
 * 图形尺寸不得占字号命名空间，layout 度量必须有真实档位。
 * 站点层的扫描（引用位是否成对、glyph/text 是否跨界）在 styleContract.test.ts。
 */
import { describe, expect, it } from 'vitest';
import { dramaTheme, layout, tokens } from '../styles/theme';

describe('§1.1 六档字阶：行高写进同一个 token', () => {
  it('六档齐备，size/leading/weight 成对', () => {
    expect(tokens.text).toEqual({
      pageTitle: { size: '28px', leading: '36px', weight: 500, weightLatin: 600 },
      sectionTitle: { size: '20px', leading: '28px', weight: 600, weightLatin: 600 },
      cardTitle: { size: '16px', leading: '24px', weight: 600, weightLatin: 600 },
      body: { size: '14px', leading: '22px', weight: 400, weightLatin: 400, weightActive: 600 },
      meta: { size: '13px', leading: '18px', weight: 400, weightLatin: 400 },
      badge: { size: '11px', leading: '14px', weight: 400, weightLatin: 400, weightActive: 600 },
    });
  });

  it('§1.2 ① 承载完整句子的最低档是 14px，13px 只给元信息', () => {
    expect(parseInt(tokens.text.body.size, 10)).toBe(14);
    expect(parseInt(tokens.text.meta.size, 10)).toBe(13);
    expect(parseInt(tokens.text.badge.size, 10)).toBe(11);
  });

  it('§1.2 ③ 中西文标题视觉等重取不同数值', () => {
    expect(tokens.text.pageTitle.weight).toBe(500);
    expect(tokens.text.pageTitle.weightLatin).toBe(600);
  });

  it('页标题对正文的落差 2.0×', () => {
    const size = (v: string): number => parseInt(v, 10);
    expect(size(tokens.text.pageTitle.size) / size(tokens.text.body.size)).toBeCloseTo(2);
  });
});

describe('§1.3 命名空间分离：font* 退役，图形归 glyph', () => {
  it('旧 font* 段整体退役，不留别名', () => {
    // fontFamilyMono 是字体族名不是字阶，逐名列干掉的才是 §1.3 要退役的那批
    const retired = [
      'fontTitleLg', 'fontTitle', 'fontBodyLg', 'fontBody', 'fontCaption', 'fontMicro',
      'fontIcon', 'fontHeading', 'fontDisplay', 'fontStat', 'fontChipIcon',
      'fontPlayGlyph', 'fontEmptyIcon', 'fontPoster',
    ] as const;
    expect(Object.keys(tokens).filter((key) => (retired as readonly string[]).includes(key))).toEqual([]);
  });

  it('glyph 段：图标与内容尺寸，取值照搬现状而非取整', () => {
    expect(tokens.glyph).toEqual({
      icon: '10px',
      iconMd: '14px',
      railIcon: '20px',
      chipIcon: '17px',
      poster: '28px',
      empty: '48px',
      brandSm: '10px',
      brandMd: '22px',
      brandBox: '40px',
      thumbW: '34px',
      thumbH: '46px',
    });
  });
});

describe('§1.4 AntD 基线必须同批改', () => {
  it('antd 的 fontSize 与 text.body 同源，否则界面一半 13 一半 14', () => {
    expect(dramaTheme.token?.fontSize).toBe(14);
  });
});

describe('§3.2 / §3.4 视觉通道与色阶必须在 token 层分得开', () => {
  /** 从 rgba(...) 里取 alpha；两档撞在一起就是三态分道白做。 */
  const alpha = (v: string): number => Number(/rgba\([^)]*,\s*([\d.]+)\)/.exec(v)?.[1] ?? -1);

  it('已勾选行底比 accentSoft 更浅一档，让铺底这一通道只服务勾选', () => {
    expect(alpha(tokens.checkedSoft)).toBeGreaterThan(0);
    expect(alpha(tokens.checkedSoft)).toBeLessThan(alpha(tokens.accentSoft));
  });

  it('状态色软底成族：success/warning/error 各一枚，取代模板拼出来的 alpha', () => {
    expect([tokens.successSoft, tokens.warningSoft, tokens.errorSoft].map(alpha)).toEqual([0.12, 0.12, 0.12]);
  });
});

describe('§2 布局度量必须有人引用', () => {
  it('导轨 / 状态栏 / 底栏 / 分栏 / 列表行高全部登记在 layout', () => {
    expect(layout.rail.width).toBe(68);
    expect(layout.statusBar.height).toBe(26);
    expect(layout.footer.height).toBe(46);
    expect(layout.row.single).toBe(36);
    expect(layout.row.double).toBe(52);
    expect(layout.split).toEqual({
      initial: 24, min: 20, max: 40, minWidth: 250, handle: 6, paddingX: tokens.spaceLg,
    });
  });

  it('间距一律落阶梯：状态栏与分栏把手的横向留白从脱阶的 14 收到 spaceLg', () => {
    expect(layout.statusBar.paddingX).toBe(tokens.spaceLg);
    expect(layout.split.paddingX).toBe(tokens.spaceLg);
  });

  it('§2 中密度对冲：卡内边距从 spaceLg 收到 spaceMd', () => {
    expect(layout.card.padding).toBe(tokens.spaceMd);
  });

  it('§2 maxWidth 1080 的裁决 = 承认内容页满宽，注释不得留第二处真相', () => {
    expect(layout.page).not.toHaveProperty('maxWidth');
  });
});
