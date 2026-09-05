import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { restartService } from '../../services/client';
import { useUiStore } from '../../stores/ui';
import { tokens } from '../../styles/theme';

const NAV_ITEMS = [
  { path: '/', label: '工作台', enabled: true },
  { path: '/projects', label: '项目管理', enabled: true },
  { path: '/models', label: '模型管理', enabled: false },
  { path: '/settings', label: '系统设置', enabled: false },
] as const;

const STATE_COLORS: Record<string, string> = {
  starting: '#FBBF24',
  ready: '#34D399',
  restarting: '#FBBF24',
  unavailable: '#F87171',
};

/** 应用壳：深色双层导航（docs/desktop/03-UI设计方案 §2.3）。 */
export function AppLayout() {
  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden', background: tokens.bgLayout }}>
      <Sidebar />
      <main style={{ flex: 1, minWidth: 0, padding: '24px 32px', overflowY: 'auto' }}>
        <Outlet />
      </main>
    </div>
  );
}

function Sidebar() {
  return (
    <aside
      style={{
        width: 220,
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        background: tokens.bgSidebar,
        borderRight: `1px solid ${tokens.borderSecondary}`,
      }}
    >
      <Logo />
      <GlobalNav />
      <ProjectNav />
      <ServiceFooter />
    </aside>
  );
}

function Logo() {
  return (
    <div
      style={{
        height: 56,
        display: 'flex',
        alignItems: 'center',
        paddingLeft: 20,
        borderBottom: `1px solid ${tokens.borderSecondary}`,
      }}
    >
      <span style={{ fontWeight: 700, fontSize: 16, color: tokens.colorPrimary }}>DramaClip</span>
    </div>
  );
}

function GlobalNav() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <nav style={{ padding: '12px 8px', display: 'flex', flexDirection: 'column', gap: 4 }}>
      {NAV_ITEMS.map((item) => (
        <NavButton
          key={item.path}
          label={item.label}
          active={location.pathname === item.path}
          disabled={!item.enabled}
          onClick={() => {
            void navigate(item.path);
          }}
        />
      ))}
    </nav>
  );
}

function ProjectNav() {
  const location = useLocation();
  const navigate = useNavigate();
  const currentProjectId = useUiStore((state) => state.currentProjectId);
  if (currentProjectId === null || !location.pathname.startsWith('/projects')) return null;
  const base = `/projects/${currentProjectId}`;
  const items = [
    { path: `${base}/analysis`, label: '智能分析' },
    { path: `${base}/modes`, label: '模式选择' },
    { path: `${base}/generate`, label: '生成导出' },
    { path: `${base}/export`, label: '导出管理' },
  ];
  return (
    <>
      <SectionDivider title="当前项目" />
      <nav style={{ padding: '4px 8px', display: 'flex', flexDirection: 'column', gap: 2 }}>
        {items.map((item) => (
          <NavButton
            key={item.path}
            label={item.label}
            indent
            active={location.pathname === item.path}
            onClick={() => {
              void navigate(item.path);
            }}
          />
        ))}
      </nav>
    </>
  );
}

function ServiceFooter() {
  const serviceState = useUiStore((state) => state.serviceState);
  return (
    <div style={{ marginTop: 'auto', padding: '12px 16px', borderTop: `1px solid ${tokens.borderSecondary}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: tokens.textSecondary }}>
        <span
          style={{ width: 8, height: 8, borderRadius: 4, background: STATE_COLORS[serviceState] ?? '#5F6570' }}
        />
        Python 服务 · {serviceState === 'ready' ? '运行中' : '启动中'}
        <button
          type="button"
          title="重启服务"
          onClick={() => {
            void restartService();
          }}
          style={{
            marginLeft: 'auto',
            background: 'none',
            border: `1px solid ${tokens.border}`,
            borderRadius: 4,
            color: tokens.textSecondary,
            fontSize: 11,
            padding: '1px 6px',
            cursor: 'pointer',
          }}
        >
          ↻
        </button>
      </div>
    </div>
  );
}

function NavButton({
  label,
  active,
  disabled = false,
  indent = false,
  onClick,
}: {
  label: string;
  active: boolean;
  disabled?: boolean;
  indent?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      style={{
        height: 40,
        textAlign: 'left',
        paddingLeft: indent ? 28 : 14,
        background: active ? 'rgba(77,159,255,0.15)' : 'transparent',
        color: disabled ? tokens.textTertiary : active ? tokens.colorPrimary : tokens.textSecondary,
        border: 'none',
        borderRadius: 6,
        fontSize: 14,
        cursor: disabled ? 'not-allowed' : 'pointer',
      }}
    >
      {label}
    </button>
  );
}

function SectionDivider({ title }: { title: string }) {
  return (
    <div
      style={{
        marginTop: 12,
        paddingTop: 10,
        paddingLeft: 16,
        borderTop: `1px solid ${tokens.borderSecondary}`,
        fontSize: 12,
        color: tokens.textTertiary,
      }}
    >
      {title}
    </div>
  );
}
