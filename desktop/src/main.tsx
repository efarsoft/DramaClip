import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { ErrorBoundary } from './app/ErrorBoundary';
import { Providers } from './app/providers';
import { Router } from './app/router';
import './styles/global.css';

const rootElement = document.getElementById('root');
if (rootElement === null) throw new Error('找不到 #root 挂载点');

createRoot(rootElement).render(
  <StrictMode>
    <ErrorBoundary>
      <Providers>
        <Router />
      </Providers>
    </ErrorBoundary>
  </StrictMode>,
);
