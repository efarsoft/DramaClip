import { HashRouter, Navigate, Route, Routes, useParams } from 'react-router-dom';
import { App } from './App';
import { HomePage } from '../features/home/HomePage';
import { ProjectsPage } from '../features/project/ProjectsPage';
import { WorkbenchPage } from '../features/analysis/WorkbenchPage';
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
          <Route path="/engines" element={<EnginesPage />} />
          <Route path="/engines/:tab" element={<EnginesPage />} />
          <Route path="/models" element={<Navigate to="/engines" replace />} />
          <Route path="/models/:tab" element={<LegacyModelTabRedirect />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/projects/:projectId/analysis" element={<WorkbenchPage />} />
          <Route path="/projects/:projectId/produce" element={<ProductionPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}

/** 旧版深链（原模型页）保住 tab 参数后转新路由。 */
function LegacyModelTabRedirect() {
  const { tab } = useParams();
  return <Navigate to={tab !== undefined ? `/engines/${tab}` : '/engines'} replace />;
}
