import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import { App } from './App';
import { HomePage } from '../features/home/HomePage';
import { ProjectsPage } from '../features/project/ProjectsPage';
import { AnalysisPage } from '../features/analysis/AnalysisPage';
import { ModePage } from '../features/narration/ModePage';
import { GeneratePage } from '../features/narration/GeneratePage';
import { ExportPage } from '../features/export/ExportPage';
import { ModelsPage } from '../features/models/ModelsPage';
import { SettingsPage } from '../features/settings/SettingsPage';

/** 路由表（docs/desktop/01 §1）。W4：全流程 项目→分析→模式→生成→导出。 */
export function Router() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<App />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/models" element={<ModelsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/projects/:projectId/analysis" element={<AnalysisPage />} />
          <Route path="/projects/:projectId/modes" element={<ModePage />} />
          <Route path="/projects/:projectId/generate" element={<GeneratePage />} />
          <Route path="/projects/:projectId/export" element={<ExportPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}
