/**
 * 路由配置
 *   /              → 创作工作台（首页，无侧边栏）
 *   /workspace/:id → 项目工作区（多步骤工作流）
 *   /settings      → 系统设置（带侧边栏）
 */

import React from 'react';
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom';
import AppLayout from './components/layout/AppLayout';
import HomePage from './pages/HomePage';
import WorkspacePage from './pages/WorkspacePage';
import SettingsPage from './pages/SettingsPage';
import ScriptExtractorPage from './pages/tools/ScriptExtractorPage';

function Router() {
  return (
    <HashRouter>
      {/* 独立页面：不需要 AppLayout 包裹 */}
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/workspace/:projectId" element={<WorkspacePage />} />

        {/* 系统设置与小工具：使用带侧边栏的 AppLayout */}
        <Route path="/" element={<AppLayout />}>
          <Route path="settings" element={<SettingsPage />} />
          <Route path="tools/extractor" element={<ScriptExtractorPage />} />
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </HashRouter>
  );
}

export default Router;
