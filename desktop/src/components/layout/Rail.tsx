/** 导轨渲染组件：从 AppLayout 抽出以便单独被 RTL 测试。 */
import { useLocation, useNavigate } from 'react-router-dom';
import type { ReactNode } from 'react';
import { NAV_GROUPS, NAV_ITEMS, isNavActive } from '../../app/navItems';
import { hoverBg } from '../../styles/mixins';
import { layout, tokens } from '../../styles/theme';

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
          style={{
            width: layout.rail.divider.width,
            height: 1,
            background: tokens.borderSecondary,
            margin: `${tokens.spaceXs} 0`,
          }}
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
          icon={<item.icon style={{ fontSize: tokens.glyph.railIcon }} />}
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
        width: layout.rail.width,
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: tokens.spaceSm,
        paddingTop: tokens.spaceMd,
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
        width: layout.rail.button.width,
        height: layout.rail.button.height,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: tokens.spaceXs,
        borderRadius: tokens.radiusControl,
        border: 'none',
        background: active ? tokens.accentSoft : 'transparent',
        color: active ? tokens.colorPrimary : tokens.textSecondary,
        cursor: 'pointer',
        transition: 'background 0.15s',
      }}
      onMouseEnter={(event) => {
        if (!active) event.currentTarget.style.background = hoverBg;
      }}
      onMouseLeave={(event) => {
        event.currentTarget.style.background = active ? tokens.accentSoft : 'transparent';
      }}
    >
      {icon}
      <span
        style={{
          fontSize: tokens.text.badge.size,
          lineHeight: tokens.text.badge.leading,
          fontWeight: active ? tokens.text.badge.weightActive : tokens.text.badge.weight,
        }}
      >
        {label}
      </span>
    </button>
  );
}
