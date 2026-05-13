/**
 * Ant Design 主题配置
 */

import type { ThemeConfig } from 'antd';

export const theme: ThemeConfig = {
  token: {
    colorPrimary: '#00d4ff',
    colorSuccess: '#10b981',
    colorWarning: '#f59e0b',
    colorError: '#ef4444',
    colorInfo: '#00d4ff',
    colorBgBase: '#0a0e1a',
    colorBgContainer: '#131829',
    colorBgElevated: '#131829',
    colorBorder: '#1e2540',
    colorBorderSecondary: '#1e2540',
    colorText: '#e0e6f0',
    colorTextSecondary: '#6b7b9d',
    colorTextTertiary: '#6b7b9d',
    borderRadius: 8,
    fontFamily:
      "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
    fontSize: 14,
    wireframe: false,
  },
  components: {
    Layout: {
      siderBg: '#131829',
      headerBg: '#131829',
      bodyBg: '#0a0e1a',
    },
    Menu: {
      darkItemBg: 'transparent',
      darkSubMenuItemBg: 'transparent',
      darkItemSelectedBg: 'rgba(0, 212, 255, 0.15)',
      darkItemHoverBg: 'rgba(0, 212, 255, 0.1)',
    },
    Card: {
      borderRadiusLG: 12,
      colorBgContainer: '#131829',
      colorBorderSecondary: '#1e2540',
    },
    Button: {
      borderRadius: 8,
    },
  },
};
