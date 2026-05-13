/**
 * 底部状态栏 — 深色科技感
 */

import React from 'react';
import { Layout, Tag, Space } from 'antd';
import { useUiStore } from '../../stores/uiStore';

const { Footer } = Layout;

const STATUS_COLORS: Record<string, string> = {
  ready: '#00d4ff',
  error: '#ff4d4f',
  default: '#faad14',
};

const STATUS_TEXTS: Record<string, string> = {
  ready: '后端就绪',
  error: '后端异常',
  default: '后端启动中...',
};

const StatusBar: React.FC = () => {
  const { backendStatus } = useUiStore();

  const color = STATUS_COLORS[backendStatus] || STATUS_COLORS.default;
  const text = STATUS_TEXTS[backendStatus] || STATUS_TEXTS.default;

  return (
    <Footer
      style={{
        background: '#0d1128',
        borderTop: '1px solid #1e2540',
        padding: '8px 24px',
        display: 'flex',
        alignItems: 'center',
      }}
    >
      <Space>
        <Tag
          style={{
            color,
            borderColor: color,
            background: 'rgba(0,0,0,0.3)',
            boxShadow: `0 0 8px ${color}44, 0 0 16px ${color}22`,
            fontWeight: 600,
          }}
        >
          {text}
        </Tag>
        <span
          style={{
            color: '#6b7b9d',
            fontSize: 12,
            fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
          }}
        >
          v1.0.0
        </span>
      </Space>
    </Footer>
  );
};

export default StatusBar;
