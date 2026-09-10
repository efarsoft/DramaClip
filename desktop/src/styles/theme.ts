import { theme as antdTheme, type ThemeConfig } from 'antd';

/**
 * 设计系统 DSS v1 唯一真相源（docs/desktop/04-设计系统方案.md）。
 * 组件禁止裸写 fontSize / borderRadius / 间距数值——一律引用本 token。
 */

export const tokens = {
  // ---- 色彩 ----
  colorPrimary: '#4D9FFF',
  colorPrimaryHover: '#6BB3FF',
  colorPrimaryActive: '#3A8AE6',
  colorAccent: '#7C5CFF',
  colorSuccess: '#34D399',
  colorWarning: '#FBBF24',
  colorError: '#F87171',
  colorInfo: '#60A5FA',
  bgSidebar: '#0B0E14',
  bgLayout: '#10141C',
  bgContainer: '#171C26',
  bgElevated: '#1F2634',
  bgInput: '#141922',
  border: '#2A3140',
  borderSecondary: '#212736',
  accentSoft: 'rgba(77,159,255,0.08)',
  gradientAccent: 'linear-gradient(135deg, #4D9FFF 0%, #7C5CFF 100%)',
  textPrimary: '#EAEEF5',
  textSecondary: '#9BA3B4',
  textTertiary: '#626B7D',
  fontFamilyMono: "'JetBrains Mono', 'Cascadia Mono', Consolas, monospace",

  // ---- 间距（4 的倍数） ----
  spaceXs: 4,
  spaceSm: 8,
  spaceMd: 12,
  spaceLg: 16,
  spaceXl: 20,
  space2xl: 24,
  space3xl: 32,

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
  fontPoster: '34px',   // 封面占位图标

  // ---- 圆角 / 层级 ----
  radiusCard: 10,
  radiusControl: 8,
  radiusChip: 999,
  radiusThumb: 6,
  radiusDot: 3,         // 圆点/竖条装饰
  shadowPop: '0 8px 24px rgba(0,0,0,0.45)',

  // ---- 布局 ----
  pageMaxWidth: 1080,
  railWidth: 68,
} as const;

/** 语义化布局度量（DSS §2）。 */
export const layout = {
  page: { maxWidth: tokens.pageMaxWidth, paddingBlock: tokens.space2xl, gap: tokens.space2xl },
  fullbleed: { paddingBlock: tokens.spaceXl, gap: tokens.spaceXl },
  card: { padding: tokens.spaceLg },
  listSection: { padding: 0, rowPadding: tokens.spaceMd },
  field: { labelWidth: 200, controlWidth: 280 },
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
    Card: { colorBorderSecondary: tokens.borderSecondary, paddingLG: tokens.spaceLg },
    Layout: { siderBg: tokens.bgSidebar, headerBg: tokens.bgLayout, bodyBg: tokens.bgLayout },
    Button: { fontWeight: 600, controlHeight: 32 },
    Table: { headerBg: tokens.bgElevated },
    Tag: { borderRadiusSM: tokens.radiusThumb },
  },
};
