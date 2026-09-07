import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import { App } from './App';
import { HomePage } from '../features/home/HomePage';
import { ProjectsPage } from '../features/project/ProjectsPage';
import { AnalysisPage } from '../features/analysis/AnalysisPage';
import { ProductionPage } from '../features/narration/ProductionPage';
import { EnginesPage } from '../features/engines/EnginesPage';
import { SettingsPage } from '../features/settings/SettingsPage';
import { WorksPage } from '../features/works/WorksPage';

/** 路由表（docs/desktop/01 §1）。W4：全流程 项目→分析→模式→生成→导出。 */
export function Router() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<App />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/works" element={<WorksPage />} />
          <Route path="/models" element={<EnginesPage />} />
          <Route path="/models/:tab" element={<EnginesPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/projects/:projectId/analysis" element={<AnalysisPage />} />
          <Route path="/projects/:projectId/produce" element={<ProductionPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}
