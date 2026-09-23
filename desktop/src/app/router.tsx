import { HashRouter, Navigate, Route, Routes, useParams } from 'react-router-dom';
import { App } from './App';
import { HomePage } from '../features/home/HomePage';
import { ProjectsPage } from '../features/project/ProjectsPage';
import { DramaShell } from '../features/project/DramaShell';
import { WorkbenchPage } from '../features/analysis/WorkbenchPage';
import { ProductionPage } from '../features/narration/ProductionPage';
import { EnginesPage } from '../features/engines/EnginesPage';
import { SettingsPage } from '../features/settings/SettingsPage';
import { WorksPage } from '../features/works/WorksPage';
import { WorksDetailPage } from '../features/works/WorksDetailPage';
import { AboutPage } from '../features/about/AboutPage';
import { LEGACY_PARAM_REDIRECTS, LEGACY_REDIRECTS } from './routes';

export function Router() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<App />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/works" element={<WorksPage />} />
          <Route path="/works/:exportId" element={<WorksDetailPage />} />
          <Route path="/engines" element={<EnginesPage />} />
          <Route path="/engines/:tab" element={<EnginesPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/about" element={<AboutPage />} />
          {/* 剧空间壳（卷三意见 06 第一刀）：组合挂载，path 字面量与 IA 登记表零漂移 */}
          <Route
            path="/projects/:projectId/analysis"
            element={
              <DramaShell>
                <WorkbenchPage />
              </DramaShell>
            }
          />
          <Route
            path="/projects/:projectId/produce"
            element={
              <DramaShell>
                <ProductionPage />
              </DramaShell>
            }
          />
          {Object.entries(LEGACY_REDIRECTS).map(([from, to]) => (
            <Route key={from} path={from} element={<Navigate to={to} replace />} />
          ))}
          {LEGACY_PARAM_REDIRECTS.map((entry) => (
            <Route
              key={entry.from}
              path={entry.from}
              element={<LegacyParamRedirect to={entry.to} />}
            />
          ))}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}

function LegacyParamRedirect({ to }: { to: string }) {
  const params = useParams();
  const filled = to.replace(/:(\w+)/g, (_match, name: string) => params[name] ?? '');
  const clean = filled.endsWith('/') ? filled.slice(0, -1) : filled;
  return <Navigate to={clean === '' ? '/' : clean} replace />;
}
