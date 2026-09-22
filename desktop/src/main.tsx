import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { ErrorBoundary } from './app/ErrorBoundary';
import { Providers } from './app/providers';
import { Router } from './app/router';
import { applyCssVars } from './styles/theme';
import './styles/global.css';

const rootElement = document.getElementById('root');
if (rootElement === null) throw new Error('找不到 #root 挂载点');
// 色值与字面栈由 theme.ts 单点导出，CSS 侧只引用 var(--dc-…)，不注入则全部悬空。
applyCssVars();

createRoot(rootElement).render(
  <StrictMode>
    <ErrorBoundary>
      <Providers>
        <Router />
      </Providers>
    </ErrorBoundary>
  </StrictMode>,
);
