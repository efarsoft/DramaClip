/**
 * DramaClip 设计系统
 * 统一管理颜色、间距、字体等设计常量
 */

export const colors = {
  // 主色调
  cyan: '#00d4ff',
  purple: '#7c3aed',

  // 背景色
  bgDeep: '#060a17',
  bgSurface: '#131829',
  bgElevated: '#1a2035',

  // 文字颜色
  textPrimary: '#e0e6ed',
  textSecondary: '#c8d0dc',
  textMuted: '#a0aec0',
  textDisabled: '#6b7b9d',

  // 状态颜色
  success: '#10b981',
  warning: '#f59e0b',
  error: '#ef4444',
  info: '#00d4ff',

  // 边框颜色
  border: 'rgba(255,255,255,0.05)',
  borderHover: 'rgba(255,255,255,0.1)',
  borderActive: 'rgba(0,212,255,0.27)',
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

export const borderRadius = {
  sm: 6,
  md: 8,
  lg: 12,
  xl: 16,
} as const;

export const card = {
  width: 240,
  padding: '36px 28px',
  borderRadius: borderRadius.xl,
} as const;

export const transitions = {
  fast: '0.15s ease',
  normal: '0.25s ease',
  slow: '0.4s cubic-bezier(0.4, 0, 0.2, 1)',
} as const;

export const shadows = {
  sm: '0 2px 8px rgba(0,0,0,0.15)',
  md: '0 4px 16px rgba(0,0,0,0.2)',
  lg: '0 8px 32px rgba(0,0,0,0.25)',
  glow: '0 0 24px rgba(0,212,255,0.2)',
} as const;

export const typography = {
  fontFamily: {
    primary: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
    mono: "'JetBrains Mono', 'Fira Code', Consolas, monospace",
  },
  fontSize: {
    xs: 11,
    sm: 12,
    md: 13,
    lg: 15,
    xl: 17,
    xxl: 20,
    xxxl: 24,
  },
  fontWeight: {
    normal: 400,
    medium: 500,
    semibold: 600,
    bold: 700,
  },
} as const;

// Emotion 颜色映射
export const emotionColors = {
  positive: '#10b981',
  negative: '#ef4444',
  neutral: '#6b7b9d',
  mixed: '#f59e0b',
} as const;

// 任务状态颜色映射
export const taskStatusColors = {
  queued: '#6b7b9d',
  running: '#00d4ff',
  completed: '#10b981',
  failed: '#ef4444',
  cancelled: '#f59e0b',
} as const;

export default {
  colors,
  spacing,
  borderRadius,
  card,
  transitions,
  shadows,
  typography,
  emotionColors,
  taskStatusColors,
};
