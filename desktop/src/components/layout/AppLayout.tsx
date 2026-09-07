import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import type { ReactNode } from 'react';
import {
  AppstoreOutlined,
  CloudServerOutlined,
  DashboardOutlined,
  ExportOutlined,
  FolderOutlined,
  RocketOutlined,
  SettingOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { restartService } from '../../services/client';
import { useUiStore } from '../../stores/ui';
import { tokens } from '../../styles/theme';

const NAV_ITEMS = [
  { path: '/', label: '工作台', icon: DashboardOutlined },
  { path: '/projects', label: '项目管理', icon: FolderOutlined },
  { path: '/models', label: '模型管理', icon: CloudServerOutlined },
  { path: '/settings', label: '系统设置', icon: SettingOutlined },
] as const;

const STATE_META: Record<string, { label: string; color: string }> = {
  starting: { label: '启动中', color: tokens.colorWarning },
  ready: { label: '运行中', color: tokens.colorSuccess },
  restarting: { label: '重启中', color: tokens.colorWarning },
  unavailable: { label: '不可用', color: tokens.colorError },
};

/** 应用壳：深色双层导航（docs/desktop/03-UI设计方案 §2.3）。 */
export function AppLayout() {
  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden', background: tokens.bgLayout }}>
      <Sidebar />
      <main style={{ flex: 1, minWidth: 0, padding: '28px 36px', overflowY: 'auto' }}>
        <Outlet />
      </main>
    </div>
  );
}

function Sidebar() {
  return (
    <aside
      style={{
        width: 224,
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
        height: 64,
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '0 20px',
        borderBottom: `1px solid ${tokens.borderSecondary}`,
      }}
    >
      <span
        style={{
          width: 30,
          height: 30,
          borderRadius: 9,
          background: tokens.gradientAccent,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 13,
          color: '#FFFFFF',
          boxShadow: '0 2px 10px rgba(77,159,255,0.35)',
        }}
      >
        ▶
      </span>
      <span style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.2 }}>
        <span style={{ fontWeight: 700, fontSize: 15, color: tokens.textPrimary }}>DramaClip</span>
        <span style={{ fontSize: 10, color: tokens.textTertiary }}>本地优先 · 短剧剪辑</span>
      </span>
    </div>
  );
}

function GlobalNav() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <nav style={{ padding: '14px 10px 6px', display: 'flex', flexDirection: 'column', gap: 4 }}>
      {NAV_ITEMS.map((item) => (
        <NavButton
          key={item.path}
          label={item.label}
          icon={<item.icon style={{ fontSize: 15 }} />}
          active={location.pathname === item.path}
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
    { path: `${base}/analysis`, label: '智能分析', icon: ThunderboltOutlined },
    { path: `${base}/modes`, label: '模式选择', icon: AppstoreOutlined },
    { path: `${base}/generate`, label: '生成导出', icon: RocketOutlined },
    { path: `${base}/export`, label: '导出管理', icon: ExportOutlined },
  ];
  return (
    <>
      <SectionDivider title="当前项目" />
      <nav style={{ padding: '6px 10px', display: 'flex', flexDirection: 'column', gap: 2 }}>
        {items.map((item) => (
          <NavButton
            key={item.path}
            label={item.label}
            icon={<item.icon style={{ fontSize: 14 }} />}
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
  const meta = STATE_META[serviceState] ?? { label: serviceState, color: tokens.textTertiary };
  return (
    <div style={{ marginTop: 'auto', padding: 12 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '10px 12px',
          borderRadius: 10,
          background: tokens.bgContainer,
          border: `1px solid ${tokens.borderSecondary}`,
        }}
      >
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: 4,
            background: meta.color,
            boxShadow: `0 0 8px ${meta.color}`,
          }}
        />
        <span style={{ fontSize: 12, color: tokens.textSecondary }}>
          Python 服务 · {meta.label}
        </span>
        <button
          type="button"
          title="重启服务"
          onClick={() => {
            void restartService();
          }}
          style={{
            marginLeft: 'auto',
            width: 24,
            height: 24,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'transparent',
            border: `1px solid ${tokens.border}`,
            borderRadius: 6,
            color: tokens.textSecondary,
            fontSize: 12,
            cursor: 'pointer',
          }}
        >
          ↻
        </button>
      </div>
    </div>
  );
}

function SectionDivider({ title }: { title: string }) {
  return (
    <div
      style={{
        marginTop: 14,
        paddingTop: 12,
        paddingLeft: 20,
        borderTop: `1px solid ${tokens.borderSecondary}`,
        fontSize: 11,
        letterSpacing: 1,
        color: tokens.textTertiary,
      }}
    >
      {title}
    </div>
  );
}

function NavButton({
  label,
  icon,
  active,
  indent = false,
  onClick,
}: {
  label: string;
  icon?: ReactNode;
  active: boolean;
  disabled?: boolean;
  indent?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        height: 38,
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        paddingLeft: indent ? 24 : 12,
        paddingRight: 12,
        background: active ? tokens.accentSoft : 'transparent',
        color: active ? tokens.colorPrimary : tokens.textSecondary,
        border: 'none',
        borderLeft: active ? `3px solid ${tokens.colorPrimary}` : '3px solid transparent',
        borderRadius: 8,
        fontSize: 13.5,
        fontWeight: active ? 600 : 400,
        cursor: 'pointer',
        transition: 'background 0.15s',
      }}
      onMouseEnter={(event) => {
        if (!active) event.currentTarget.style.background = tokens.bgElevated;
      }}
      onMouseLeave={(event) => {
        if (!active) event.currentTarget.style.background = 'transparent';
      }}
    >
      {icon}
      {label}
    </button>
  );
}
