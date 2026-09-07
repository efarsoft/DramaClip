/** 自定义标题栏：拖拽区 + 项目搜索 + 窗口控制（frame:false 配套）。 */
import { useEffect, useState, type CSSProperties } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { BorderOutlined, CloseOutlined, MinusOutlined, SearchOutlined } from '@ant-design/icons';
import { projectApi, windowControl } from '../../services/client';
import { tokens } from '../../styles/theme';

export function TitleBar(): React.ReactElement {
  const location = useLocation();
  const onProjectArea = location.pathname.startsWith('/projects');
  return (
    <div
      style={{
        height: 46,
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        paddingLeft: 14,
        background: tokens.bgSidebar,
        borderBottom: `1px solid ${tokens.borderSecondary}`,
        WebkitAppRegion: 'drag',
      } as CSSProperties}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span
          style={{
            width: 22,
            height: 22,
            borderRadius: 7,
            background: tokens.gradientAccent,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 10,
            color: '#FFFFFF',
          }}
        >
          ▶
        </span>
        <span style={{ fontWeight: 700, fontSize: 13, color: tokens.textPrimary }}>DramaClip</span>
      </div>
      {onProjectArea ? (
        <ProjectSearch />
      ) : (
        <span style={{ fontSize: 11, color: tokens.textTertiary }}>
          左侧选择工作区，进入项目后可在此快速跳转
        </span>
      )}
      <WindowButtons />
    </div>
  );
}

const SEARCH_ICON = (
  <SearchOutlined
    style={{ position: 'absolute', left: 9, top: 7, fontSize: 13, color: tokens.textTertiary }}
  />
);

const SEARCH_BADGE = (
  <span
    style={{
      position: 'absolute',
      right: 8,
      top: 5,
      fontSize: 10,
      padding: '1px 6px',
      borderRadius: 4,
      border: `1px solid ${tokens.border}`,
      color: tokens.textTertiary,
    }}
  >
    项目
  </span>
);

const SEARCH_INPUT_STYLE: CSSProperties = {
  width: '100%',
  height: 28,
  paddingLeft: 28,
  paddingRight: 44,
  borderRadius: 7,
  border: `1px solid ${tokens.border}`,
  background: tokens.bgInput,
  color: tokens.textPrimary,
  fontSize: 12,
  outline: 'none',
};

interface ProjectOption {
  readonly id: string;
  readonly name: string;
}

function ProjectSearch(): React.ReactElement {
  const navigate = useNavigate();
  const [keyword, setKeyword] = useState('');
  const [items, setItems] = useState<ProjectOption[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const lower = keyword.toLowerCase();
    void projectApi
      .list()
      .then((all) => {
        setItems(all.filter((p) => p.name.toLowerCase().includes(lower)).slice(0, 6));
      })
      .catch(() => {
        setItems([]);
      });
  }, [keyword, open]);

  return (
    <div
      style={{ position: 'relative', width: 340, WebkitAppRegion: 'no-drag' } as CSSProperties}
    >
      <input
        value={keyword}
        placeholder="搜索项目…"
        onChange={(event) => {
          setKeyword(event.target.value);
        }}
        onFocus={() => {
          setOpen(true);
        }}
        onBlur={() => {
          window.setTimeout(() => {
            setOpen(false);
          }, 150);
        }}
        style={SEARCH_INPUT_STYLE}
      />
      {SEARCH_ICON}
      {SEARCH_BADGE}
      {open && items.length > 0 && (
        <SearchResults
          items={items}
          onPick={(path) => {
            void navigate(path);
          }}
        />
      )}
    </div>
  );
}

function SearchResults({
  items,
  onPick,
}: {
  items: readonly ProjectOption[];
  onPick: (path: string) => void;
}) {
  return (
    <div
      style={{
        position: 'absolute',
        top: 34,
        left: 0,
        right: 0,
        zIndex: 30,
        borderRadius: 8,
        border: `1px solid ${tokens.border}`,
        background: tokens.bgElevated,
        boxShadow: '0 8px 24px rgba(0,0,0,0.45)',
        overflow: 'hidden',
      }}
    >
      {items.map((item) => (
        <div
          key={item.id}
          onMouseDown={() => {
            onPick(`/projects/${item.id}/analysis`);
          }}
          style={{
            padding: '8px 12px',
            fontSize: 12.5,
            color: tokens.textSecondary,
            cursor: 'pointer',
          }}
          onMouseEnter={(event) => {
            event.currentTarget.style.background = tokens.accentSoft;
          }}
          onMouseLeave={(event) => {
            event.currentTarget.style.background = 'transparent';
          }}
        >
          {item.name}
        </div>
      ))}
    </div>
  );
}

function WindowButtons() {
  const make = (
    label: React.ReactNode,
    action: 'minimize' | 'maximize-toggle' | 'close',
    hover: string,
  ) => (
    <button
      type="button"
      onClick={() => {
        void windowControl(action);
      }}
      style={{
        width: 44,
        height: '100%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'transparent',
        border: 'none',
        color: tokens.textSecondary,
        fontSize: 11,
        cursor: 'pointer',
        WebkitAppRegion: 'no-drag',
      } as CSSProperties}
      onMouseEnter={(event) => {
        event.currentTarget.style.background = hover;
      }}
      onMouseLeave={(event) => {
        event.currentTarget.style.background = 'transparent';
      }}
    >
      {label}
    </button>
  );
  return (
    <div style={{ marginLeft: 'auto', display: 'flex', height: '100%' }}>
      {make(<MinusOutlined />, 'minimize', tokens.bgElevated)}
      {make(<BorderOutlined style={{ fontSize: 9 }} />, 'maximize-toggle', tokens.bgElevated)}
      {make(<CloseOutlined />, 'close', '#C43A3A')}
    </div>
  );
}
