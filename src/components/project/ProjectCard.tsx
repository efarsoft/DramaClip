/**
 * 项目卡片组件
 * 深色科技感设计：暗色卡片、青色悬浮发光边框、状态标签霓虹效果、暗红删除按钮
 */

import React from 'react';
import { Card, Typography, Space, Tooltip } from 'antd';
import { FolderOpenOutlined, DeleteOutlined, VideoCameraOutlined } from '@ant-design/icons';
import type { Project } from '../../services/ipc';

const { Text, Paragraph } = Typography;

// 深色科幻配色常量
const COLORS = {
  bg: '#0a0e1a',           // 主背景
  surface: '#131829',      // 卡片表面
  surfaceHover: '#1a2035', // 悬停表面
  primary: '#00d4ff',      // 青色主色（发光）
  primaryDim: 'rgba(0, 212, 255, 0.15)',   // 青色淡背景
  primaryBorder: 'rgba(0, 212, 255, 0.4)', // 青色边框
  textPrimary: '#e2e8f0',  // 主文本
  textSecondary: '#64748b', // 次要文本
  deleteRed: '#8b0000',    // 暗红删除
  deleteRedHover: '#ff4d4f',
};

// 科技感字体
const SCI_FI_FONT = "'Orbitron', 'Share Tech Mono', 'Consolas', monospace";

interface ProjectCardProps {
  project: Project;
  onOpen: (project: Project) => void;
  onDelete: (project: Project) => void;
}

/** 状态标签霓虹发光颜色 */
const STATUS_GLOW_COLORS: Record<string, { bg: string; text: string; glow: string }> = {
  empty:      { bg: 'rgba(100, 116, 139, 0.2)', text: '#64748b', glow: '#64748b' },
  idle:       { bg: 'rgba(148, 163, 184, 0.2)', text: '#94a3b8', glow: '#94a3b8' },
  analyzing:  { bg: 'rgba(255, 170, 0, 0.2)',   text: '#ffaa00', glow: '#ffaa00' },
  ready:      { bg: 'rgba(0, 255, 136, 0.2)',   text: '#00ff88', glow: '#00ff88' },
  clipping:   { bg: 'rgba(255, 102, 0, 0.2)',   text: '#ff6600', glow: '#ff6600' },
  exporting:  { bg: 'rgba(0, 212, 255, 0.2)',   text: '#00d4ff', glow: '#00d4ff' },
};

const getProjectStatus = (project: Project): string => {
  if (!project.episode_count) return 'empty';
  switch (project.status) {
    case 'analyzing': return 'analyzing';
    case 'ready': return 'ready';
    case 'clipping': return 'clipping';
    case 'exporting': return 'exporting';
    default: return 'idle';
  }
};

const getStatusLabel = (status: string): string => {
  const labels: Record<string, string> = {
    empty: '空项目',
    idle: '待分析',
    analyzing: '分析中',
    ready: '就绪',
    clipping: '剪辑中',
    exporting: '导出中',
  };
  return labels[status] || status;
};

export const ProjectCard: React.FC<ProjectCardProps> = ({ project, onOpen, onDelete }) => {
  const statusKey = getProjectStatus(project);
  const statusTheme = STATUS_GLOW_COLORS[statusKey] || STATUS_GLOW_COLORS.empty;
  const glow = `0 0 8px ${statusTheme.glow}, 0 0 16px ${statusTheme.glow}40`;
  const isReady = statusKey === 'ready';

  return (
    <Card
      hoverable
      onClick={() => onOpen(project)}
      style={{
        background: COLORS.surface,
        border: `1px solid ${isReady ? COLORS.primaryBorder : 'rgba(30, 40, 60, 0.6)'}`,
        borderRadius: 8,
        cursor: 'pointer',
        transition: 'all 0.3s ease',
        boxShadow: isReady ? `0 0 12px ${COLORS.primary}20, 0 4px 20px rgba(0, 0, 0, 0.4)` : '0 4px 12px rgba(0, 0, 0, 0.3)',
        position: 'relative',
        overflow: 'hidden',
        fontFamily: SCI_FI_FONT,
      }}
      styles={{
        body: { padding: '16px 20px' },
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = COLORS.primaryBorder;
        e.currentTarget.style.background = COLORS.surfaceHover;
        e.currentTarget.style.boxShadow = `0 0 20px ${COLORS.primary}30, 0 8px 32px rgba(0, 0, 0, 0.5)`;
        e.currentTarget.style.transform = 'translateY(-2px)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = isReady ? COLORS.primaryBorder : 'rgba(30, 40, 60, 0.6)';
        e.currentTarget.style.background = COLORS.surface;
        e.currentTarget.style.boxShadow = isReady ? `0 0 12px ${COLORS.primary}20, 0 4px 20px rgba(0, 0, 0, 0.4)` : '0 4px 12px rgba(0, 0, 0, 0.3)';
        e.currentTarget.style.transform = 'translateY(0)';
      }}
      actions={[
        <Tooltip title="打开项目" key="open">
          <span
            onClick={(e) => { e.stopPropagation(); onOpen(project); }}
            style={{
              color: COLORS.primary,
              fontSize: 18,
              cursor: 'pointer',
              transition: 'all 0.2s',
              textShadow: `0 0 8px ${COLORS.primary}60`,
            }}
            onMouseEnter={(e) => { e.currentTarget.style.textShadow = `0 0 12px ${COLORS.primary}`; e.currentTarget.style.transform = 'scale(1.15)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.textShadow = `0 0 8px ${COLORS.primary}60`; e.currentTarget.style.transform = 'scale(1)'; }}
          >
            <FolderOpenOutlined />
          </span>
        </Tooltip>,
        <Tooltip title="删除项目" key="delete">
          <span
            onClick={(e) => { e.stopPropagation(); onDelete(project); }}
            style={{
              color: COLORS.deleteRed,
              fontSize: 18,
              cursor: 'pointer',
              transition: 'all 0.2s',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = COLORS.deleteRedHover;
              e.currentTarget.style.textShadow = `0 0 8px ${COLORS.deleteRedHover}80`;
              e.currentTarget.style.transform = 'scale(1.15)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = COLORS.deleteRed;
              e.currentTarget.style.textShadow = 'none';
              e.currentTarget.style.transform = 'scale(1)';
            }}
          >
            <DeleteOutlined />
          </span>
        </Tooltip>,
      ]}
    >
      {/* 顶部装饰线 */}
      <div style={{
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        height: 2,
        background: `linear-gradient(90deg, transparent, ${COLORS.primary}, transparent)`,
        opacity: isReady ? 0.6 : 0.2,
        transition: 'opacity 0.3s',
      }} />

      <Card.Meta
        title={
          <Text strong style={{
            color: COLORS.textPrimary,
            fontSize: 16,
            fontFamily: SCI_FI_FONT,
            letterSpacing: '0.5px',
          }} ellipsis>
            {project.name}
          </Text>
        }
        description={
          <>
            <Paragraph ellipsis={{ rows: 2 }} style={{
              marginBottom: 12,
              color: COLORS.textSecondary,
              fontSize: 12,
              fontFamily: "'Consolas', 'Courier New', monospace",
            }}>
              {project.path}
            </Paragraph>
            <Space size="large" style={{ width: '100%', justifyContent: 'space-between' }}>
              {/* 状态标签 - 霓虹发光 */}
              <span style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '4px 12px',
                background: statusTheme.bg,
                border: `1px solid ${statusTheme.glow}40`,
                borderRadius: 4,
                color: statusTheme.text,
                fontSize: 12,
                fontFamily: SCI_FI_FONT,
                textShadow: glow,
                boxShadow: glow,
                transition: 'all 0.3s',
              }}>
                <span style={{
                  display: 'inline-block',
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: statusTheme.glow,
                  boxShadow: `0 0 6px ${statusTheme.glow}`,
                  animation: statusKey === 'analyzing' || statusKey === 'clipping' || statusKey === 'exporting'
                    ? 'pulse 1.5s ease-in-out infinite'
                    : 'none',
                }} />
                {getStatusLabel(statusKey)}
              </span>
              {/* 视频计数 */}
              <span style={{
                color: COLORS.textSecondary,
                fontSize: 12,
                display: 'flex',
                alignItems: 'center',
                gap: 4,
              }}>
                <VideoCameraOutlined style={{ color: COLORS.primary, textShadow: `0 0 6px ${COLORS.primary}40` }} />
                <Text style={{ fontFamily: SCI_FI_FONT }}>{project.episode_count}</Text>
                <span style={{ fontFamily: SCI_FI_FONT, opacity: 0.7 }}>VID</span>
              </span>
            </Space>
          </>
        }
      />
    </Card>
  );
};

export default ProjectCard;

// 脉冲动画（通过内联样式注入）
const styleTag = document.createElement('style');
styleTag.textContent = `
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }
`;
if (!document.querySelector('#project-card-animations')) {
  styleTag.id = 'project-card-animations';
  document.head.appendChild(styleTag);
}
