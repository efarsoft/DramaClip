/** W2·2 对比度矩阵门禁（2026-10-16 规格 §2.2）：前景与五档底色**从 theme 实读**
 * （import tokens = 单一真相源），逐档断言最低比值：正文档 ≥4.5、非文字装饰 ≥2.5 棘轮底。
 *
 * 装饰豁免说明：decorativeMuted 被规格 §2.1 钉在旧值 #5E6C8C（对 bgElevated 2.88:1），
 * 服务纯装饰位（曲线刻度 fill）；WCAG 1.4.11 对纯装饰豁免数值门——**状态指示器不在此列**，
 * 它们必须用达标文字档（CloudConfigSection 圆点用 textTertiary 4.79:1 实证）。
 * 新登记的前景/底色 token 必须进矩阵，否则断言面缺行即红。
 */
import { describe, expect, it } from 'vitest';
import { tokens } from '../styles/theme';

function luminance(hex: string): number {
  const value = hex.replace('#', '');
  const channel = (offset: number): number => {
    const raw = Number.parseInt(value.slice(offset, offset + 2), 16) / 255;
    return raw <= 0.03928 ? raw / 12.92 : ((raw + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(0) + 0.7152 * channel(2) + 0.0722 * channel(4);
}

function contrast(foreground: string, background: string): number {
  const a = luminance(foreground);
  const b = luminance(background);
  const [hi, lo] = a >= b ? [a, b] : [b, a];
  return (hi + 0.05) / (lo + 0.05);
}

const TEXT_TIERS: Readonly<Record<string, string>> = {
  textPrimary: tokens.textPrimary,
  textSecondary: tokens.textSecondary,
  textTertiary: tokens.textTertiary,
};

const BACKGROUNDS: Readonly<Record<string, string>> = {
  bgSidebar: tokens.bgSidebar,
  bgLayout: tokens.bgLayout,
  bgContainer: tokens.bgContainer,
  bgElevated: tokens.bgElevated,
  bgInput: tokens.bgInput,
};

for (const value of [...Object.values(TEXT_TIERS), ...Object.values(BACKGROUNDS)]) {
  if (value === undefined) throw new Error('对比度矩阵引用了不存在的 token');
}

describe('W2·2 对比度矩阵（从 theme 实读，底色五档全组合）', () => {
  it('正文档三档对每档底色 ≥4.5:1', () => {
    for (const [fgName, fg] of Object.entries(TEXT_TIERS)) {
      for (const [bgName, bg] of Object.entries(BACKGROUNDS)) {
        expect(contrast(fg, bg), `${fgName} on ${bgName}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it('decorativeMuted（装饰豁免档）有棘轮底：不许无声变暗', () => {
    for (const [bgName, bg] of Object.entries(BACKGROUNDS)) {
      expect(contrast(tokens.decorativeMuted, bg), `decorativeMuted on ${bgName}`).toBeGreaterThanOrEqual(2.5);
    }
  });
});
