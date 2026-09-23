import { Button, Result, Space } from 'antd';
import { Component, type PropsWithChildren, type ReactNode } from 'react';
import { restartService } from '../services/client';

interface ErrorBoundaryState {
  error: Error | null;
  /** 复制按钮的三态：失败也说出来，不假装已复制。 */
  copyState: 'idle' | 'copied' | 'failed';
  restarting: boolean;
}

const COPY_LABEL: Readonly<Record<ErrorBoundaryState['copyState'], string>> = {
  idle: '复制错误',
  copied: '已复制',
  failed: '复制失败，请手动截图',
};

/**
 * 渲染层崩溃兜底：防白屏之外给出全部恢复出口（卷二 P-A 三补）——
 * 复制错误原文（报障带证据）、重启 Python 服务（崩因常在服务侧）、回工作台（不重载也能走）。
 */
export class ErrorBoundary extends Component<PropsWithChildren, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { error: null, copyState: 'idle', restarting: false };

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { error, copyState: 'idle' };
  }

  override componentDidCatch(error: Error): void {
    // 经渲染层 console 转发链路进入主进程日志
    console.error('[boundary] 渲染崩溃:', error.message, error.stack ?? '');
  }

  private copyDetail(): void {
    const error = this.state.error;
    if (error === null) return;
    const detail = `${error.message}\n\n${error.stack ?? ''}`;
    navigator.clipboard
      .writeText(detail)
      .then(() => {
        this.setState({ copyState: 'copied' });
      })
      .catch(() => {
        this.setState({ copyState: 'failed' });
      });
  }

  private restart(): void {
    this.setState({ restarting: true });
    restartService()
      .then(() => {
        // 服务重启后渲染树里的旧数据多半已失效：清掉崩溃态回工作台重新拉
        this.setState({ error: null, restarting: false });
        window.location.hash = '#/';
      })
      .catch(() => {
        this.setState({ restarting: false });
      });
  }

  private backHome(): void {
    this.setState({ error: null, copyState: 'idle' });
    window.location.hash = '#/';
  }

  override render(): ReactNode {
    const { error, copyState, restarting } = this.state;
    if (error !== null) {
      return (
        <Result
          status="error"
          title="界面出了点问题"
          subTitle={error.message}
          extra={
            <Space wrap>
              <Button
                type="primary"
                onClick={() => {
                  this.setState({ error: null, copyState: 'idle' });
                  window.location.reload();
                }}
              >
                重新加载
              </Button>
              <Button
                loading={restarting}
                onClick={() => {
                  this.restart();
                }}
              >
                重启服务
              </Button>
              <Button
                onClick={() => {
                  this.copyDetail();
                }}
              >
                {COPY_LABEL[copyState]}
              </Button>
              <Button
                onClick={() => {
                  this.backHome();
                }}
              >
                回工作台
              </Button>
            </Space>
          }
        />
      );
    }
    return this.props.children;
  }
}
