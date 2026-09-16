/** DSS v1 布局骨架：页面壳 / 页头 / 分区 / 向导底栏（docs/desktop/04 §2）。 */
import type { CSSProperties, ReactNode } from 'react';
import { Button } from 'antd';
import { LeftOutlined, RightOutlined } from '@ant-design/icons';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';

/** 页面容器：内容页 1080 居中；fullbleed 供向导型工作台。 */
export function PageShell({
  children,
  fullbleed = false,
}: {
  children: ReactNode;
  fullbleed?: boolean;
}): React.ReactElement {
  const style = fullbleed
    ? { ...mixins.pageShell(true), gap: tokens.spaceXl, padding: `${String(tokens.spaceXl)} 0` }
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
              fontSize: tokens.fontTitleLg,
              fontWeight: 700,
              color: tokens.textPrimary,
            }}
          >
            {title}
          </h1>
          {chip !== undefined && <span style={mixins.chip()}>{chip}</span>}
        </div>
        {desc !== undefined && (
          <div style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary, marginTop: tokens.spaceSm }}>
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
            padding: `${String(tokens.spaceMd)} ${String(tokens.spaceLg)}`,
            borderBottom: `1px solid ${tokens.borderSecondary}`,
          }}
        >
          <span style={mixins.sectionBar()} />
          <span
            style={{
              fontSize: tokens.fontTitle,
              fontWeight: 600,
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

/** 向导页底栏：上一步 / 进度文案 / 下一步。 */
export function PageFooter({
  step,
  total,
  canProceed,
  proceedHint,
  nextLabel,
  onPrev,
  onNext,
}: {
  step: number;
  total: number;
  canProceed: boolean;
  proceedHint: string;
  nextLabel: string;
  onPrev: () => void;
  onNext: () => void;
}): React.ReactElement {
  return (
    <div
      style={{
        height: 46,
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        gap: tokens.spaceMd,
        padding: `0 ${String(tokens.spaceLg)}`,
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
      <span style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary }}>
        步骤 {String(step)} / {String(total)} · {proceedHint}
      </span>
      <Button type="primary" style={{ marginLeft: 'auto' }} disabled={!canProceed} onClick={onNext}>
        下一步：{nextLabel}
        <RightOutlined style={{ fontSize: tokens.fontMicro }} />
      </Button>
    </div>
  );
}
