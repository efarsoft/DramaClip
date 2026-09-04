import { theme as antdTheme, type ThemeConfig } from 'antd';

/**
 * 设计 token（视觉权威：docs/desktop/03-UI设计方案.md §3）。
 * antd ConfigProvider 映射为主，禁止手写 antd 已有控件。
 */
export const tokens = {
  colorPrimary: '#4D9FFF',
  colorPrimaryHover: '#6BB3FF',
  colorPrimaryActive: '#3A8AE6',
  colorSuccess: '#34D399',
  colorWarning: '#FBBF24',
  colorError: '#F87171',
  colorInfo: '#60A5FA',
  bgSidebar: '#0F1115',
  bgLayout: '#161920',
  bgContainer: '#1E2128',
  bgElevated: '#252830',
  bgInput: '#1A1D24',
  border: '#333740',
  borderSecondary: '#2A2D35',
  textPrimary: '#E8EAED',
  textSecondary: '#9AA0A8',
  textTertiary: '#5F6570',
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
    borderRadius: 6,
  },
  components: {
    Card: { colorBorderSecondary: tokens.border },
    Layout: { siderBg: tokens.bgSidebar, headerBg: tokens.bgLayout, bodyBg: tokens.bgLayout },
    Button: { fontWeight: 600 },
  },
};
