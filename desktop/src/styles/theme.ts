import { theme as antdTheme, type ThemeConfig } from 'antd';

/**
 * 设计系统 DSS v1 唯一真相源（docs/desktop/04-设计系统方案.md）。
 * 组件禁止裸写 fontSize / borderRadius / 间距数值——一律引用本 token。
 */

/** 间距基础值：antd 组件 token 只收 number，px 字符串 token 由此派生（单一真相源）。 */
const SPACING = { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, xxl: 24, xxxl: 32, xxxxl: 64 } as const;

export const tokens = {
  // ---- 色彩 ----
  colorPrimary: '#7C9CFF',
  colorPrimaryHover: '#93AEFF',
  colorPrimaryActive: '#6A8AE8',
  colorAccent: '#9B7BFF',
  colorSuccess: '#34D399',
  colorWarning: '#FBBF24',
  colorError: '#F87171',
  colorInfo: '#60A5FA',
  colorWhite: '#FFFFFF',
  bgSidebar: '#0A0F1E',
  bgLayout: '#0F1526',
  bgContainer: '#161E33',
  bgElevated: '#1C2540',
  bgInput: '#131A2E',
  border: '#2A3550',
  borderSecondary: '#1F2942',
  accentSoft: 'rgba(124,156,255,0.12)',
  gradientAccent: 'linear-gradient(135deg, #6D9BFF 0%, #9B7BFF 100%)',
  textPrimary: '#F0F4FF',
  textSecondary: '#A8B4CE',
  textTertiary: '#5E6C8C',
  fontFamilyMono: "'JetBrains Mono', 'Cascadia Mono', Consolas, monospace",

  // ---- 间距（px 字符串，模板插值安全） ----
  spaceXs: `${String(SPACING.xs)}px`,
  spaceSm: `${String(SPACING.sm)}px`,
  spaceMd: `${String(SPACING.md)}px`,
  spaceLg: `${String(SPACING.lg)}px`,
  spaceXl: `${String(SPACING.xl)}px`,
  space2xl: `${String(SPACING.xxl)}px`,
  space3xl: `${String(SPACING.xxxl)}px`,
  space4xl: `${String(SPACING.xxxxl)}px`,

  // ---- 字号 ----
  fontTitleLg: '22px',
  fontTitle: '15px',
  fontBodyLg: '14px',
  fontBody: '13px',
  fontCaption: '12px',
  fontMicro: '11px',
  fontIcon: '10px',     // 小图标/角标
  fontHeading: '20px',  // 页面级标题
  fontDisplay: '24px',  // 问候语等大号展示
  fontStat: '26px',     // 统计芯片大数字
  fontChipIcon: '17px', // 统计芯片图标
  fontPlayGlyph: '28px', // 海报占位播放图标
  fontEmptyIcon: '48px', // 空态图标（DSS §3.5）
  fontPoster: '34px',   // 封面占位图标

  // ---- 圆角 / 层级 ----
  radiusCard: 14,
  radiusControl: 10,
  radiusChip: 999,
  radiusThumb: 6,
  radiusDot: 3,         // 圆点/竖条装饰
  shadowPop: '0 12px 32px rgba(0,0,0,0.45)',
  shadowCard: '0 6px 20px rgba(4,8,20,0.35)',

  // ---- 布局 ----
  railWidth: 68,
} as const;

/** 语义化布局度量（DSS §2）。 */
export const layout = {
  page: { paddingBlock: tokens.space2xl, gap: tokens.space2xl },
  fullbleed: { paddingBlock: tokens.spaceXl, gap: tokens.spaceXl },
  card: { padding: tokens.spaceLg },
  listSection: { padding: 0, rowPadding: tokens.spaceMd },
  field: { labelWidth: 250, controlWidth: 320 },
  controlHeight: { sm: 28, md: 32 },
} as const;

export const dramaTheme: ThemeConfig = {
  algorithm: antdTheme.darkAlgorithm,
  token: {
    colorPrimary: tokens.colorPrimary,
    colorSuccess: tokens.colorSuccess,
    colorWarning: tokens.colorWarning,
    colorError: tokens.colorError,
    colorInfo: tokens.colorInfo,
    colorBgBase: tokens.bgLayout,
    colorBgContainer: tokens.bgContainer,
    colorBgElevated: tokens.bgElevated,
    colorBorder: tokens.border,
    colorBorderSecondary: tokens.borderSecondary,
    colorText: tokens.textPrimary,
    colorTextSecondary: tokens.textSecondary,
    colorTextTertiary: tokens.textTertiary,
    borderRadius: tokens.radiusControl,
    fontSize: 13,
  },
  components: {
    Card: { colorBorderSecondary: tokens.borderSecondary, paddingLG: SPACING.lg },
    Layout: { siderBg: tokens.bgSidebar, headerBg: tokens.bgLayout, bodyBg: tokens.bgLayout },
    Button: { fontWeight: 600, controlHeight: 32 },
    Table: { headerBg: tokens.bgElevated },
    Tag: { borderRadiusSM: tokens.radiusThumb },
  },
};
