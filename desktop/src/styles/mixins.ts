/**
 * DSS v1 布局 mixin（docs/desktop/04 §1-2）。
 * 返回 CSSProperties；页面/卡片结构一律经此生成，禁止手写散值。
 */
import type { CSSProperties } from 'react';
import { tokens } from './theme';

export const mixins = {
  pageShell,
  pageHeaderRow,
  sectionTitleRow,
  sectionBar,
  cardBody,
  fieldRow,
  fieldLabelCol,
  fieldControlCol,
  listRow,
  chip,
  statusDot,
} as const;

/** 页面壳：内容页（1080 居中）或全屏向导页（fullbleed）。 */
export function pageShell(fullbleed = false): CSSProperties {
  const base: CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    overflowY: 'auto',
  };
  if (fullbleed) return base;
  return {
    ...base,
    width: '100%',
    gap: tokens.space2xl,
  };
}

/** 页头行：标题组在左、动作槽在右。 */
export function pageHeaderRow(): CSSProperties {
  return { display: 'flex', alignItems: 'flex-end', gap: tokens.spaceMd };
}

/** 分区标题行：渐变竖条 + 标题 + extra 槽。 */
export function sectionTitleRow(): CSSProperties {
  return { display: 'flex', alignItems: 'center', minHeight: 22 };
}

export function sectionBar(): CSSProperties {
  return { width: 3, height: 13, borderRadius: 2, background: tokens.gradientAccent };
}

/** 卡片内容区内边距（列表型传 dense=true 置 0，行内自理）。 */
export function cardBody(dense = false): CSSProperties {
  return dense
    ? { padding: 0 }
    : { padding: tokens.spaceLg };
}

/** 表单字段行：标签列 + 控件列（DSS §3.2 唯一结构）。 */
export function fieldRow(): CSSProperties {
  return {
    display: 'flex',
    alignItems: 'flex-start',
    gap: tokens.space2xl,
    padding: `${String(tokens.spaceMd)} 0`,
  };
}

export function fieldLabelCol(): CSSProperties {
  return { width: 250, flexShrink: 0, paddingTop: 6 };
}

export function fieldControlCol(): CSSProperties {
  return { width: 320, flexShrink: 0 };
}

/** 通用列表行（素材/能力/出片记录同构）。 */
export function listRow(active = false): CSSProperties {
  return {
    display: 'flex',
    alignItems: 'center',
    gap: tokens.spaceMd,
    padding: `0 ${String(tokens.spaceMd)}`,
    borderBottom: `1px solid ${tokens.borderSecondary}`,
    background: active ? tokens.accentSoft : 'transparent',
  };
}

/** 悬浮态（背景 + 主色描边，非阴影）。 */
export const hoverBg = tokens.accentSoft;

/** 状态点：6px + 同色微光。 */
export function statusDot(color: string): CSSProperties {
  return {
    width: 6,
    height: 6,
    borderRadius: 3,
    background: color,
    boxShadow: `0 0 6px ${color}`,
    flexShrink: 0,
  };
}

/** 信息芯片（胶囊）。 */
export function chip(): CSSProperties {
  return {
    fontSize: tokens.fontMicro,
    padding: `2px ${String(tokens.spaceSm)}`,
    borderRadius: tokens.radiusChip,
    background: tokens.bgElevated,
    color: tokens.textSecondary,
    flexShrink: 0,
  };
}
