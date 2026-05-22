/**
 * 错误边界组件
 * 捕获子组件树的 JavaScript 错误，显示降级 UI
 */

import React, { Component, ErrorInfo, ReactNode } from 'react';
import { Result, Button, Typography } from 'antd';
import { WarningOutlined } from '@ant-design/icons';

const { Text } = Typography;

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
}

interface State {
  hasError: boolean;
  error?: Error;
  errorInfo?: ErrorInfo;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    this.setState({ errorInfo });

    // 记录错误日志
    console.error('[ErrorBoundary] Caught error:', error, errorInfo);

    // 调用错误回调
    if (this.props.onError) {
      this.props.onError(error, errorInfo);
    }
  }

  handleReload = (): void => {
    this.setState({ hasError: false, error: undefined, errorInfo: undefined });
    window.location.reload();
  };

  handleGoHome = (): void => {
    this.setState({ hasError: false, error: undefined, errorInfo: undefined });
    window.location.hash = '#/';
  };

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      const errorMessage = this.state.error?.message || '未知错误';

      return (
        <Result
          status="error"
          icon={<WarningOutlined style={{ color: '#ff4d4f' }} />}
          title="页面加载失败"
          subTitle={
            <div style={{ textAlign: 'center', maxWidth: 400 }}>
              <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
                {errorMessage}
              </Text>
              {process.env.NODE_ENV === 'development' && this.state.errorInfo && (
                <details style={{
                  textAlign: 'left',
                  marginTop: 16,
                  padding: 12,
                  background: '#fff7e6',
                  borderRadius: 8,
                  fontSize: 12,
                  maxHeight: 200,
                  overflow: 'auto'
                }}>
                  <summary style={{ cursor: 'pointer', fontWeight: 500, marginBottom: 8 }}>
                    错误详情（开发模式）
                  </summary>
                  <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                    {this.state.error?.stack}
                  </pre>
                </details>
              )}
            </div>
          }
          extra={[
            <Button key="reload" type="primary" onClick={this.handleReload}>
              刷新页面
            </Button>,
            <Button key="home" onClick={this.handleGoHome}>
              返回首页
            </Button>,
          ]}
        />
      );
    }

    return this.props.children;
  }
}

// 简化版本 - 用于包裹单个组件
interface SimpleErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
}

export const SimpleErrorBoundary: React.FC<SimpleErrorBoundaryProps> = ({
  children,
  fallback,
}) => {
  const [error, setError] = React.useState<Error | null>(null);

  React.useEffect(() => {
    const handleError = (event: ErrorEvent) => {
      setError(new Error(event.message));
    };

    window.addEventListener('error', handleError);
    return () => window.removeEventListener('error', handleError);
  }, []);

  if (error) {
    if (fallback) return <>{fallback}</>;

    return (
      <Result
        status="warning"
        title="组件加载失败"
        subTitle={error.message}
        extra={
          <Button size="small" onClick={() => setError(null)}>
            重试
          </Button>
        }
      />
    );
  }

  return <>{children}</>;
};

export default ErrorBoundary;
