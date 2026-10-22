/** 组件家族原型 1/3（规格 §3.3）：四态区块（空/载入/失败/就绪）——收掉各写各的
 * 空态与自制错误横幅。失败态可带重试；就绪态渲染 children。
 * 载入态的 Spin 自带文案（W1 门禁 G4：裸转圈禁令）。
 */
import { Button, Empty, Spin } from 'antd';
import type { ReactElement, ReactNode } from 'react';
import { tokens } from '../../styles/theme';

export type StateBlockState = 'loading' | 'error' | 'empty' | 'ready';

export function StateBlock({
  state,
  errorText = '加载失败',
  emptyText = '暂无内容',
  loadingText = '正在加载',
  onRetry,
  children,
}: {
  state: StateBlockState;
  /** 失败态的原因原文（所见原则：不收进 Tooltip）。 */
  errorText?: string;
  emptyText?: string;
  loadingText?: string;
  /** 失败态的重试动作；提供才显示按钮。 */
  onRetry?: () => void;
  children?: ReactNode;
}): ReactElement {
  if (state === 'loading') {
    return (
      <div style={{ textAlign: 'center', padding: tokens.spaceXl, color: tokens.textTertiary }}>
        <Spin /> {loadingText}
      </div>
    );
  }
  if (state === 'error') {
    return (
      <div style={{ textAlign: 'center', padding: tokens.spaceXl, color: tokens.colorError }}>
        {errorText}
        {onRetry !== undefined && (
          <div style={{ marginTop: tokens.spaceSm }}>
            <Button size="small" onClick={onRetry}>
              重试
            </Button>
          </div>
        )}
      </div>
    );
  }
  if (state === 'empty') {
    return <Empty description={emptyText} styles={{ image: { height: 60 } }} />;
  }
  return <>{children}</>;
}
