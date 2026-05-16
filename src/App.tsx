/**
 * 应用根组件
 */

import React, { useEffect } from 'react';
import { App as AntdApp } from 'antd';
import Router from './router';
import { useUiStore } from './stores/uiStore';

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
    <AntdApp>
      <Router />
    </AntdApp>
  );
}

export default App;
