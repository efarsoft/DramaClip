import { Button, Result } from 'antd';
import { Component, type PropsWithChildren, type ReactNode } from 'react';

interface ErrorBoundaryState {
  error: Error | null;
}

/** 渲染层崩溃兜底：防止白屏，提供恢复出口（docs/05 规约"错误边界"项）。 */
export class ErrorBoundary extends Component<PropsWithChildren, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error): void {
    // 经渲染层 console 转发链路进入主进程日志
    console.error('[boundary] 渲染崩溃:', error.message, error.stack ?? '');
  }

  render(): ReactNode {
    if (this.state.error !== null) {
      return (
        <Result
          status="error"
          title="界面出了点问题"
          subTitle={this.state.error.message}
          extra={
            <Button
              type="primary"
              onClick={() => {
                this.setState({ error: null });
                window.location.reload();
              }}
            >
              重新加载
            </Button>
          }
        />
      );
    }
    return this.props.children;
  }
}
