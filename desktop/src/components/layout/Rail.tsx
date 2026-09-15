/** 导轨渲染组件：从 AppLayout 抽出以便单独被 RTL 测试。 */
import { useLocation, useNavigate } from 'react-router-dom';
import type { ReactNode } from 'react';
import { NAV_GROUPS, NAV_ITEMS, isNavActive } from '../../app/navItems';
import { tokens } from '../../styles/theme';

export function Rail() {
  const location = useLocation();
  const navigate = useNavigate();

  const groups: ReactNode[] = [];
  for (let gi = 0; gi < NAV_GROUPS.length; gi++) {
    const group = NAV_GROUPS[gi];
    if (group === undefined) continue;
    // 上组贴顶、下组钉底（规格 §2.1：配置与元信息沉底，桌面软件惯例）；
    // 分隔线随下组走在钉底块之前。
    const pinnedBottom = gi > 0;
    if (pinnedBottom) {
      groups.push(<div key="spacer" style={{ flex: 1 }} />);
      groups.push(
        <div
          key="divider"
          style={{ width: 40, height: 1, background: tokens.borderSecondary, margin: '4px 0' }}
        />,
      );
    }
    for (const item of NAV_ITEMS) {
      if (item.group !== group) continue;
      const active = isNavActive(item, location.pathname);
      groups.push(
        <RailButton
          key={item.path}
          label={item.label}
          icon={<item.icon style={{ fontSize: tokens.fontHeading }} />}
          active={active}
          onClick={() => {
            void navigate(item.path);
          }}
        />,
      );
    }
  }

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
      {groups}
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
