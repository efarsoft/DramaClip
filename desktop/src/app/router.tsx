import { Suspense, lazy } from 'react';
import { HashRouter, Navigate, Route, Routes, useParams } from 'react-router-dom';
import { App } from './App';
import { HomePage } from '../features/home/HomePage';
import { DramaShell } from '../features/project/DramaShell';
import { LEGACY_PARAM_REDIRECTS, LEGACY_REDIRECTS } from './routes';
import { tokens } from '../styles/theme';

// ── 路由级代码分割（UI 改善批①）：重页面按需加载，首屏 bundle 显著瘦身 ──
// 首屏只载 HomePage（工作台）+ DramaShell（壳），其余页面首次导航才拉 chunk。
// Suspense fallback 用轻量文字占位（无动画），chunk 通常 <50ms 即就绪。
const ProjectsPage = lazy(() =>
  import('../features/project/ProjectsPage').then((m) => ({ default: m.ProjectsPage })));
const WorkbenchPage = lazy(() =>
  import('../features/analysis/WorkbenchPage').then((m) => ({ default: m.WorkbenchPage })));
const ProductionPage = lazy(() =>
  import('../features/narration/ProductionPage').then((m) => ({ default: m.ProductionPage })));
const EnginesPage = lazy(() =>
  import('../features/engines/EnginesPage').then((m) => ({ default: m.EnginesPage })));
const SettingsPage = lazy(() =>
  import('../features/settings/SettingsPage').then((m) => ({ default: m.SettingsPage })));
const WorksPage = lazy(() =>
  import('../features/works/WorksPage').then((m) => ({ default: m.WorksPage })));
const ToolsPage = lazy(() =>
  import('../features/tools/ToolsPage').then((m) => ({ default: m.ToolsPage })));
const WorksDetailPage = lazy(() =>
  import('../features/works/WorksDetailPage').then((m) => ({ default: m.WorksDetailPage })));
const AboutPage = lazy(() =>
  import('../features/about/AboutPage').then((m) => ({ default: m.AboutPage })));

/** 路由 chunk 加载中的占位：轻量文字（秒级感知，不做花哨动画）。 */
function RouteFallback(): React.ReactElement {
  return (
    <div style={{ padding: `${tokens.space4xl} ${tokens.space2xl}`, textAlign: 'center', color: tokens.textSecondary }}>
      加载中…
    </div>
  );
}

function Lazy({ children }: { children: React.ReactElement }): React.ReactElement {
  return <Suspense fallback={<RouteFallback />}>{children}</Suspense>;
}

export function Router() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<App />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/dramas" element={<Lazy><ProjectsPage /></Lazy>} />
          <Route path="/works" element={<Lazy><WorksPage /></Lazy>} />
          <Route path="/works/:exportId" element={<Lazy><WorksDetailPage /></Lazy>} />
          <Route path="/tools" element={<Lazy><ToolsPage /></Lazy>} />
          <Route path="/engines" element={<Lazy><EnginesPage /></Lazy>} />
          <Route path="/engines/:tab" element={<Lazy><EnginesPage /></Lazy>} />
          <Route path="/settings" element={<Lazy><SettingsPage /></Lazy>} />
          <Route path="/about" element={<Lazy><AboutPage /></Lazy>} />
          {/* 剧空间壳（卷三意见 06 第一刀）：组合挂载，path 字面量与 IA 登记表零漂移 */}
          {/* 剧空间合一（W3·§3.2-1）：单路由两区块，阶段条变纯锚点 */}
          <Route
            path="/drama/:projectId"
            element={
              <DramaShell
                analysis={<Lazy><WorkbenchPage /></Lazy>}
                produce={<Lazy><ProductionPage /></Lazy>}
              />
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
