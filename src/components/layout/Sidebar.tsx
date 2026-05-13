/**
 * 导航侧边栏 - 深色科技感设计
 */

import React, { useEffect, useRef } from 'react';
import { Layout, Menu } from 'antd';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  FolderOutlined,
  SettingOutlined,
  CloseOutlined,
} from '@ant-design/icons';

const { Sider } = Layout;

// 深色科技感配色
const SIDEBAR_BG = '#0d1128';
const PRIMARY_COLOR = '#00d4ff';
const ACCENT_COLOR = '#7c3aed';
const SURFACE_COLOR = '#131829';

// 全局样式注入
const injectStyles = () => {
  const styleId = 'sidebar-sci-fi-styles';
  if (document.getElementById(styleId)) return;

  const style = document.createElement('style');
  style.id = styleId;
  style.textContent = `
    /* DramaClip 渐变标题 */
    .sidebar-logo-text {
      background: linear-gradient(135deg, #00d4ff 0%, #00e5ff 30%, #00b8d4 60%, #7c3aed 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      filter: drop-shadow(0 0 8px rgba(0, 212, 255, 0.4));
      animation: logo-glow 3s ease-in-out infinite alternate;
    }

    @keyframes logo-glow {
      0% { filter: drop-shadow(0 0 6px rgba(0, 212, 255, 0.3)); }
      100% { filter: drop-shadow(0 0 14px rgba(0, 212, 255, 0.6)); }
    }

    /* 关闭按钮 */
    .sidebar-close-btn {
      position: absolute;
      top: 12px;
      right: 12px;
      width: 28px;
      height: 28px;
      display: flex;
      align-items: center;
      justify-content: center;
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 6px;
      cursor: pointer;
      color: rgba(255, 255, 255, 0.5);
      background: transparent;
      transition: all 0.25s ease;
      z-index: 10;
    }

    .sidebar-close-btn:hover {
      color: #ff4d4f;
      border-color: rgba(255, 77, 79, 0.5);
      background: rgba(255, 77, 79, 0.1);
      box-shadow: 0 0 12px rgba(255, 77, 79, 0.3);
    }

    /* 菜单项悬停发光 */
    .sidebar-menu .ant-menu-item:hover {
      background-color: rgba(0, 212, 255, 0.08) !important;
      color: ${PRIMARY_COLOR} !important;
      box-shadow:
        inset 2px 0 8px rgba(0, 212, 255, 0.2),
        0 0 12px rgba(0, 212, 255, 0.15);
      border-radius: 4px;
    }

    .sidebar-menu .ant-menu-item-active {
      background-color: rgba(0, 212, 255, 0.12) !important;
      color: ${PRIMARY_COLOR} !important;
      box-shadow:
        inset 3px 0 12px rgba(0, 212, 255, 0.25),
        0 0 16px rgba(0, 212, 255, 0.2);
    }

    .sidebar-menu .ant-menu-item-selected {
      background-color: rgba(0, 212, 255, 0.15) !important;
      color: ${PRIMARY_COLOR} !important;
      box-shadow:
        inset 3px 0 12px rgba(0, 212, 255, 0.3),
        0 0 20px rgba(0, 212, 255, 0.25);
      border-radius: 4px;
      font-weight: 500;
    }

    .sidebar-menu .ant-menu-item-selected::after {
      display: none;
    }

    /* 滚动条美化 */
    .sidebar-menu::-webkit-scrollbar {
      width: 4px;
    }

    .sidebar-menu::-webkit-scrollbar-track {
      background: transparent;
    }

    .sidebar-menu::-webkit-scrollbar-thumb {
      background: rgba(0, 212, 255, 0.3);
      border-radius: 2px;
    }

    .sidebar-menu::-webkit-scrollbar-thumb:hover {
      background: rgba(0, 212, 255, 0.5);
    }

    /* 侧边栏整体渐变边框 */
    .sidebar-sider::before {
      content: '';
      position: absolute;
      top: 0;
      right: 0;
      width: 1px;
      height: 100%;
      background: linear-gradient(
        to bottom,
        transparent 0%,
        ${PRIMARY_COLOR} 20%,
        ${ACCENT_COLOR} 80%,
        transparent 100%
      );
      opacity: 0.4;
      filter: blur(1px);
    }

    /* 菜单分割线样式 */
    .sidebar-menu .ant-menu-item {
      margin: 4px 8px;
      border-radius: 6px;
      transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }

    /* 图标发光 */
    .sidebar-menu .ant-menu-item:hover .anticon,
    .sidebar-menu .ant-menu-item-selected .anticon {
      filter: drop-shadow(0 0 6px rgba(0, 212, 255, 0.6));
    }

    /* 顶部区域装饰线 */
    .sidebar-header-deco {
      position: absolute;
      bottom: 0;
      left: 0;
      right: 0;
      height: 1px;
      background: linear-gradient(
        90deg,
        transparent 0%,
        ${PRIMARY_COLOR} 50%,
        transparent 100%
      );
      opacity: 0.3;
    }
  `;
  document.head.appendChild(style);
};

const menuItems = [
  { key: '/', icon: <FolderOutlined />, label: '创作工作台' },
  { key: '/settings', icon: <SettingOutlined />, label: '系统设置' },
];

interface SidebarProps {
  onCollapse?: (collapsed: boolean) => void;
  collapsed?: boolean;
}

const Sidebar: React.FC<SidebarProps> = ({ onCollapse, collapsed }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const styleInjected = useRef(false);

  useEffect(() => {
    if (!styleInjected.current) {
      injectStyles();
      styleInjected.current = true;
    }
  }, []);

  // 处理关闭按钮点击 - 发送 IPC 调用主进程关闭窗口
  const handleClose = () => {
    // 尝试通过 electron API 关闭窗口
    if (window.electronAPI?.window?.close) {
      window.electronAPI.window.close();
    }
    // 浏览器回退
    else if (window.history.length > 1) {
      window.history.back();
    }
  };

  return (
    <Sider
      width={200}
      collapsedWidth={0}
      theme="dark"
      collapsible
      collapsed={collapsed}
      onCollapse={onCollapse}
      style={{
        height: '100vh',
        position: 'fixed',
        left: 0,
        top: 0,
        background: SIDEBAR_BG,
        zIndex: 1000,
      }}
      className="sidebar-sider"
    >
      {/* 关闭按钮 */}
      <div className="sidebar-close-btn" onClick={handleClose} title="关闭侧边栏">
        <CloseOutlined style={{ fontSize: 14 }} />
      </div>

      {/* Logo 区域 */}
      <div
        style={{
          height: 64,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          position: 'relative',
        }}
      >
        <span className="sidebar-logo-text" style={{ fontSize: 20, fontWeight: 'bold' }}>
          DramaClip
        </span>
        <div className="sidebar-header-deco" />
      </div>

      {/* 菜单 */}
      <Menu
        theme="dark"
        mode="inline"
        selectedKeys={[location.pathname]}
        items={menuItems}
        onClick={({ key }) => navigate(key)}
        className="sidebar-menu"
        style={{
          borderRight: 0,
          background: 'transparent',
          paddingTop: 8,
        }}
      />
    </Sider>
  );
};

export default Sidebar;
