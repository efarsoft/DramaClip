import { App as AntdApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import type { PropsWithChildren } from 'react';
import { dramaTheme } from '../styles/theme';

/** 全局 Provider 组合：antd 深色主题 + 消息上下文（docs/desktop/01 §6）。 */
export function Providers({ children }: PropsWithChildren) {
  return (
    <ConfigProvider locale={zhCN} theme={dramaTheme}>
      <AntdApp>{children}</AntdApp>
    </ConfigProvider>
  );
}
