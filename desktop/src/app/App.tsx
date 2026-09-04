import { useEffect } from 'react';
import { Outlet } from 'react-router-dom';
import { onServiceEvent } from '../services/client';
import { useUiStore } from '../stores/ui';
import { tokens } from '../styles/theme';

/** 应用壳：W1 极简版（顶栏 + 状态点 + 内容区）；侧边栏随 W3 工作台落地。 */
export function App() {
  const setServiceState = useUiStore((state) => state.setServiceState);

  useEffect(
    () =>
      onServiceEvent((event) => {
        if (event.type === 'service-state') setServiceState(event.state);
      }),
    [setServiceState],
  );

  return (
    <div style={{ minHeight: '100vh', background: tokens.bgLayout }}>
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '0 24px',
          height: 48,
          borderBottom: `1px solid ${tokens.borderSecondary}`,
        }}
      >
        <span style={{ fontWeight: 700, color: tokens.textPrimary }}>DramaClip</span>
        <span style={{ fontSize: 12, color: tokens.textTertiary }}>短剧自动高光剪辑 · v2</span>
      </header>
      <main style={{ padding: 24 }}>
        <Outlet />
      </main>
    </div>
  );
}
