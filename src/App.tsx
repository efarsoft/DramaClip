/**
 * 应用根组件
 */

import React, { useEffect, lazy, Suspense } from 'react';
import { App as AntdApp, Spin } from 'antd';
import Router from './router';
import { useUiStore } from './stores/uiStore';
import ErrorBoundary from './components/common/ErrorBoundary';

const PageLoader: React.FC = () => (
  <div style={{
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    height: '100vh',
    background: '#060a17',
  }}>
    <Spin size="large" tip="加载中..." />
  </div>
);

function App() {
  const { setBackendStatus } = useUiStore();

  useEffect(() => {
    // 监听后端就绪状态
    if (window.electronAPI) {
      const unsubscribe = window.electronAPI.backend.onReady(() => {
        console.log('[App] Backend is ready');
        setBackendStatus('ready');
      });

      const unsubscribeError = window.electronAPI.backend.onError((error) => {
        console.error('[App] Backend error:', error);
        setBackendStatus('error');
      });

      return () => {
        unsubscribe();
        unsubscribeError();
      };
    }
  }, [setBackendStatus]);

  return (
    <ErrorBoundary fallback={<PageLoader />}>
      <AntdApp>
        <Suspense fallback={<PageLoader />}>
          <Router />
        </Suspense>
      </AntdApp>
    </ErrorBoundary>
  );
}

export default App;
