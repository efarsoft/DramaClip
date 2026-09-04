import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import { App } from './App';
import { StatusPage } from '../features/home/StatusPage';

/** 路由表（docs/desktop/01 §1）。W1 仅首页状态页，其余随阶段落地。 */
export function Router() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<App />}>
          <Route path="/" element={<StatusPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}
