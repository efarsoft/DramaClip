/** 应用壳：自定义标题栏 + 图标导航栏 + 内容 + 底部状态栏。 */
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import type { ReactNode } from 'react';
import {
  CloudServerOutlined,
  DashboardOutlined,
  FolderOutlined,
  PlaySquareOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import { tokens } from '../../styles/theme';
import { StatusBar } from './StatusBar';
import { TitleBar } from './TitleBar';

const NAV_ITEMS = [
  { path: '/', label: '工作台', icon: DashboardOutlined },
  { path: '/projects', label: '项目', icon: FolderOutlined },
  { path: '/works', label: '作品', icon: PlaySquareOutlined },
  { path: '/models', label: '模型', icon: CloudServerOutlined },
  { path: '/settings', label: '设置', icon: SettingOutlined },
] as const;

export function AppLayout() {
  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <TitleBar />
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        <Rail />
        <main style={{ flex: 1, minWidth: 0, overflowY: 'auto', padding: '22px 28px' }}>
          <Outlet />
        </main>
      </div>
      <StatusBar />
    </div>
  );
}

function Rail() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <nav
      style={{
        width: 68,
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 6,
        paddingTop: 12,
        background: tokens.bgSidebar,
        borderRight: `1px solid ${tokens.borderSecondary}`,
      }}
    >
      {NAV_ITEMS.map((item) => (
        <RailButton
          key={item.path}
          label={item.label}
          icon={<item.icon style={{ fontSize: tokens.fontHeading }} />}
          active={location.pathname === item.path}
          onClick={() => {
            void navigate(item.path);
          }}
        />
      ))}
    </nav>
  );
}

function RailButton({
  label,
  icon,
  active,
  onClick,
}: {
  label: string;
  icon: ReactNode;
  active: boolean;
  onClick: () => void;
}): React.ReactElement {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        width: 54,
        height: 52,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 3,
        borderRadius: tokens.fontIcon,
        border: 'none',
        background: active ? tokens.accentSoft : 'transparent',
        color: active ? tokens.colorPrimary : tokens.textSecondary,
        cursor: 'pointer',
        transition: 'background 0.15s',
      }}
      onMouseEnter={(event) => {
        if (!active) event.currentTarget.style.background = tokens.bgElevated;
      }}
      onMouseLeave={(event) => {
        event.currentTarget.style.background = active ? tokens.accentSoft : 'transparent';
      }}
    >
      {icon}
      <span style={{ fontSize: tokens.fontIcon, fontWeight: active ? 600 : 400 }}>{label}</span>
    </button>
  );
}
