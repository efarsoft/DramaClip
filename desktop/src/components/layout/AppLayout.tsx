/** 应用壳：自定义标题栏 + 图标导航栏 + 内容 + 底部状态栏。 */
import { tokens } from '../../styles/theme';
import { Outlet } from 'react-router-dom';
import { Rail } from './Rail';
import { StatusBar } from './StatusBar';
import { TitleBar } from './TitleBar';

export function AppLayout() {
  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <TitleBar />
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        <Rail />
        <main style={{ flex: 1, minWidth: 0, overflowY: 'auto', padding: `${tokens.spaceXl} ${tokens.space2xl}` }}>
          <Outlet />
        </main>
      </div>
      <StatusBar />
    </div>
  );
}
