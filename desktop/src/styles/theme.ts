import { theme as antdTheme, type ThemeConfig } from 'antd';

/**
 * 设计 token（视觉权威：docs/desktop/03-UI设计方案.md §3）。
 * antd ConfigProvider 映射为主，禁止手写 antd 已有控件。
 */
export const tokens = {
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
  accentSoft: 'rgba(77,159,255,0.13)',
  gradientAccent: 'linear-gradient(135deg, #4D9FFF 0%, #7C5CFF 100%)',
  textPrimary: '#EAEEF5',
  textSecondary: '#9BA3B4',
  textTertiary: '#626B7D',
  fontFamilyMono: "'JetBrains Mono', 'Cascadia Mono', Consolas, monospace",
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
    borderRadius: 8,
    fontSize: 13,
  },
  components: {
    Card: {
      colorBorderSecondary: tokens.borderSecondary,
      paddingLG: 20,
    },
    Layout: { siderBg: tokens.bgSidebar, headerBg: tokens.bgLayout, bodyBg: tokens.bgLayout },
    Button: { fontWeight: 600, controlHeight: 34 },
    Table: { headerBg: tokens.bgElevated },
    Tag: { borderRadiusSM: 4 },
  },
};
