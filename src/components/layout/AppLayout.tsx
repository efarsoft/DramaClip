/**
 * 应用整体布局 — 深色科技感
 * 用于系统设置等需要侧边栏的页面
 *
 * Sidebar 组件自身渲染 Sider（fixed 定位），内容区域通过 marginLeft 避让
 */

import React from 'react';
import { Layout } from 'antd';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import StatusBar from './StatusBar';

const { Content } = Layout;

/* ─── 深色科技风 AppLayout ─── */
const SIDEBAR_WIDTH = 200;

const styles: Record<string, React.CSSProperties> = {
  wrapper: {
    minHeight: '100vh',
    width: '100%',
    background: '#0a0e1a',
    display: 'flex',
  },
  contentLayout: {
    marginLeft: SIDEBAR_WIDTH,
    background: '#0a0e1a',
    display: 'flex',
    flexDirection: 'column' as const,
    flex: 1,
    minHeight: '100vh',
  },
  content: {
    flex: 1,
    padding: 0,
    background: '#0a0e1a',
    overflowY: 'auto',
  },
  footer: {
    height: 36,
    background: 'rgba(0, 0, 0, 0.35)',
    backdropFilter: 'blur(10px)',
    WebkitBackdropFilter: 'blur(10px)',
    borderTop: '1px solid rgba(255,255,255,0.06)',
    padding: '0 24px',
    display: 'flex',
    alignItems: 'center',
  },
};

const AppLayout: React.FC = () => {
  return (
    <Layout style={styles.wrapper}>
      <Sidebar />
      <div style={styles.contentLayout}>
        <Content style={styles.content}>
          <Outlet />
        </Content>
        <Layout.Footer style={styles.footer}>
          <StatusBar />
        </Layout.Footer>
      </div>
    </Layout>
  );
};

export default AppLayout;
