/** DSS v1 布局骨架：页面壳 / 页头 / 分区 / 向导底栏（规格 §1–§3）。 */
import type { CSSProperties, ReactNode } from 'react';
import { Button, Tooltip } from 'antd';
import { LeftOutlined, RightOutlined } from '@ant-design/icons';
import { mixins } from '../../styles/mixins';
import { layout, tokens } from '../../styles/theme';

/** 页面容器：内容页满宽（§2）；fullbleed 供向导型工作台。 */
export function PageShell({
  children,
  fullbleed = false,
}: {
  children: ReactNode;
  fullbleed?: boolean;
}): React.ReactElement {
  const style = fullbleed
    ? { ...mixins.pageShell(true), gap: layout.fullbleed.gap, padding: `${layout.fullbleed.paddingBlock} 0` }
    : mixins.pageShell();
  return <div style={style}>{children}</div>;
}

/** 页头：标题 + 描述 + 右侧动作槽（primary 每屏至多 1 个）。 */
export function PageHeader({
  title,
  desc,
  chip,
  onBack,
  actions,
}: {
  title: string;
  desc?: string;
  chip?: string;
  onBack?: () => void;
  actions?: ReactNode;
}): React.ReactElement {
  return (
    <header style={mixins.pageHeaderRow()}>
      {onBack !== undefined && (
        <Button size="small" icon={<LeftOutlined />} onClick={onBack}>
          返回
        </Button>
      )}
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceMd }}>
          <h1
            style={{
              margin: 0,
              fontSize: tokens.text.pageTitle.size,
              lineHeight: tokens.text.pageTitle.leading,
              fontWeight: tokens.text.pageTitle.weight,
              color: tokens.textPrimary,
            }}
          >
            {title}
          </h1>
          {chip !== undefined && <span style={mixins.chip()}>{chip}</span>}
        </div>
        {desc !== undefined && (
          <div
            style={{
              fontSize: tokens.text.body.size,
              lineHeight: tokens.text.body.leading,
              color: tokens.textTertiary,
              marginTop: tokens.spaceSm,
            }}
          >
            {desc}
          </div>
        )}
      </div>
      {actions !== undefined && (
        <div style={{ marginLeft: 'auto', display: 'flex', gap: tokens.spaceSm, flexShrink: 0 }}>
          {actions}
        </div>
      )}
    </header>
  );
}

/** 分区卡：渐变竖条标题 + 可选 extra 槽（文字链/开关）。 */
export function PageSection({
  title,
  extra,
  dense = false,
  style,
  children,
}: {
  title?: string;
  extra?: ReactNode;
  dense?: boolean;
  style?: CSSProperties;
  children: ReactNode;
}): React.ReactElement {
  return (
    <section
      style={{
        background: tokens.bgContainer,
        border: `1px solid ${tokens.borderSecondary}`,
        borderRadius: tokens.radiusCard,
        boxShadow: tokens.shadowCard,
        ...style,
      }}
    >
      {title !== undefined && (
        <div
          style={{
            ...mixins.sectionTitleRow(),
            padding: `${tokens.spaceMd} ${tokens.spaceLg}`,
            borderBottom: `1px solid ${tokens.borderSecondary}`,
          }}
        >
          <span style={mixins.sectionBar()} />
          <span
            style={{
              fontSize: tokens.text.cardTitle.size,
              lineHeight: tokens.text.cardTitle.leading,
              fontWeight: tokens.text.cardTitle.weight,
              color: tokens.textPrimary,
              marginLeft: tokens.spaceSm,
            }}
          >
            {title}
          </span>
          {extra !== undefined && (
            <span style={{ marginLeft: 'auto' }}>{extra}</span>
          )}
        </div>
      )}
      <div style={mixins.cardBody(dense)}>{children}</div>
    </section>
  );
}

/** 向导页底栏：上一步 / 进度文案 / 下一步（禁用时给出解锁条件）。 */
export function PageFooter({
  step,
  total,
  canProceed,
  proceedHint,
  lockedHint,
  nextLabel,
  onPrev,
  onNext,
}: {
  step: number;
  total: number;
  canProceed: boolean;
  proceedHint: string;
  /** 未满足推进条件时悬停给出的原因；不传则不给提示。 */
  lockedHint?: string;
  nextLabel: string;
  onPrev: () => void;
  onNext: () => void;
}): React.ReactElement {
  return (
    <div
      style={{
        height: layout.footer.height,
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        gap: tokens.spaceMd,
        padding: `0 ${layout.footer.paddingX}`,
        background: tokens.bgSidebar,
        borderTop: `1px solid ${tokens.borderSecondary}`,
      }}
    >
      <Button
        icon={<RightOutlined style={{ transform: 'rotate(180deg)' }} />}
        disabled={step <= 1}
        onClick={onPrev}
      >
        上一步
      </Button>
      <span
        style={{
          fontSize: tokens.text.meta.size,
          lineHeight: tokens.text.meta.leading,
          color: tokens.textTertiary,
        }}
      >
        步骤 {String(step)} / {String(total)} · {proceedHint}
      </span>
      <Tooltip title={canProceed ? '' : (lockedHint ?? '')}>
        <Button type="primary" style={{ marginLeft: 'auto' }} disabled={!canProceed} onClick={onNext}>
          下一步：{nextLabel}
          <RightOutlined style={{ fontSize: tokens.glyph.icon }} />
        </Button>
      </Tooltip>
    </div>
  );
}
