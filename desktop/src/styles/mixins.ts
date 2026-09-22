/**
 * DSS v1 布局 mixin（规格 2026-09-21 §1–§3）。
 * 返回 CSSProperties；页面/卡片结构一律经此生成，禁止手写散值。
 * 度量取自 theme.ts 的 layout/text/glyph，本文件不另起数字。
 */
import type { CSSProperties } from 'react';
import { layout, tokens } from './theme';

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

/** 页面壳：内容页满宽（§2 裁决：1080 居中从未实现过），fullbleed 供向导型工作台。 */
export function pageShell(fullbleed = false): CSSProperties {
  const base: CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    overflowY: 'auto',
  };
  if (fullbleed) return base;
  return { ...base, width: '100%', gap: layout.page.gap };
}

/** 页头行：标题组在左、动作槽在右。 */
export function pageHeaderRow(): CSSProperties {
  return { display: 'flex', alignItems: 'flex-end', gap: tokens.spaceMd };
}

/**
 * 分区标题行：最小高度派生自卡级标题的行高（§2「派生自字阶而非另起数字」）——
 * 原先写死的 22 比新的 24px 行高还矮，是个已经追不上字阶的残留。
 */
export function sectionTitleRow(): CSSProperties {
  return { display: 'flex', alignItems: 'center', minHeight: tokens.text.cardTitle.leading };
}

export function sectionBar(): CSSProperties {
  return {
    width: layout.sectionBar.width,
    height: layout.sectionBar.height,
    borderRadius: tokens.radiusDot,
    background: tokens.gradientAccent,
    flexShrink: 0,
  };
}

/** 卡片内容区内边距（列表型传 dense=true 置 0，行内自理）。 */
export function cardBody(dense = false): CSSProperties {
  return dense ? { padding: 0 } : { padding: layout.card.padding };
}

/** 表单字段行：标签列 + 控件列（DSS §3.2 唯一结构）。 */
export function fieldRow(): CSSProperties {
  return {
    display: 'flex',
    alignItems: 'flex-start',
    gap: layout.page.gap,
    padding: `${tokens.spaceMd} 0`,
  };
}

export function fieldLabelCol(): CSSProperties {
  return { width: layout.field.labelWidth, flexShrink: 0, paddingTop: layout.field.labelPaddingTop };
}

export function fieldControlCol(): CSSProperties {
  return { width: layout.field.controlWidth, flexShrink: 0 };
}

/**
 * 三态分道（§3.2）：三种「被强调」的原因走三条互不相干的通道。
 * 已勾选 = 铺底（唯一使用铺底的语义），当前查看 = 左 3px 竖条，悬停 = 只换背景。
 * 两个入参各写各的，撞在一起时用户分不清自己在勾选还是在浏览——这正是改前的形状。
 * rows=2 给名称 + 元信息两行的行，行高派生自字阶（22×2 + 8 = 52）。
 * padding 只有横向：上下留白由行高给，再叠纵向 padding 会顶破固定行高（§2 中密度）。
 * 用 minHeight 不用 height——解说文案这类行会折行变高，固定高度会把文字裁掉。
 */
export function listRow(state: { checked?: boolean; active?: boolean; rows?: 1 | 2 } = {}): CSSProperties {
  return {
    display: 'flex',
    alignItems: 'center',
    position: 'relative',
    minHeight: state.rows === 2 ? layout.row.double : layout.row.single,
    gap: tokens.spaceMd,
    padding: `0 ${tokens.spaceMd}`,
    borderBottom: `1px solid ${tokens.borderSecondary}`,
    background: state.checked ? tokens.checkedSoft : 'transparent',
    boxShadow: state.active
      ? `inset ${String(layout.sectionBar.width)}px 0 0 ${tokens.colorPrimary}`
      : 'none',
  };
}

/** 悬浮态：中性一档，把 accentSoft/checkedSoft 让给勾选与选中，不再同色。 */
export const hoverBg = tokens.bgElevated;

/** 状态点：6px + 同色微光。组件里禁止再手抄这组度量。 */
export function statusDot(color: string): CSSProperties {
  return {
    width: 6,
    height: 6,
    borderRadius: tokens.radiusDot,
    background: color,
    boxShadow: `0 0 6px ${color}`,
    flexShrink: 0,
  };
}

/** 信息芯片（胶囊）。 */
export function chip(): CSSProperties {
  return {
    fontSize: tokens.text.badge.size,
    lineHeight: tokens.text.badge.leading,
    padding: `${String(layout.chip.paddingBlock)}px ${layout.chip.paddingInline}`,
    borderRadius: tokens.radiusChip,
    background: tokens.bgElevated,
    color: tokens.textSecondary,
    flexShrink: 0,
  };
}
