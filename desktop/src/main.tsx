import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Providers } from './app/providers';
import { Router } from './app/router';
import './styles/global.css';

const rootElement = document.getElementById('root');
if (rootElement === null) throw new Error('找不到 #root 挂载点');

createRoot(rootElement).render(
  <StrictMode>
    <Providers>
      <Router />
    </Providers>
  </StrictMode>,
);
