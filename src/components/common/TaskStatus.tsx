/**
 * 通用任务状态标签组件
 * 统一管理任务状态的显示
 */

import React from 'react';
import { Tag } from 'antd';
import {
  CheckCircleFilled,
  CloseCircleOutlined,
  ClockCircleOutlined,
  LoadingOutlined,
  MinusCircleOutlined,
  ExclamationCircleOutlined,
  SyncOutlined,
} from '@ant-design/icons';

export type TaskStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'pending' | 'idle';

interface TaskStatusConfig {
  color: string;
  icon: React.ReactNode;
  label: string;
  bgColor: string;
}

const DEFAULT_STATUS_MAP: Record<TaskStatus, TaskStatusConfig> = {
  queued: {
    color: '#6b7b9d',
    bgColor: 'rgba(107, 123, 157, 0.1)',
    icon: <ClockCircleOutlined />,
    label: '排队中',
  },
  pending: {
    color: '#6b7b9d',
    bgColor: 'rgba(107, 123, 157, 0.1)',
    icon: <ClockCircleOutlined />,
    label: '等待中',
  },
  idle: {
    color: '#6b7b9d',
    bgColor: 'rgba(107, 123, 157, 0.1)',
    icon: <ClockCircleOutlined />,
    label: '空闲',
  },
  running: {
    color: '#00d4ff',
    bgColor: 'rgba(0, 212, 255, 0.1)',
    icon: <LoadingOutlined />,
    label: '处理中',
  },
  completed: {
    color: '#10b981',
    bgColor: 'rgba(16, 185, 129, 0.1)',
    icon: <CheckCircleFilled />,
    label: '已完成',
  },
  failed: {
    color: '#ef4444',
    bgColor: 'rgba(239, 68, 68, 0.1)',
    icon: <CloseCircleOutlined />,
    label: '失败',
  },
  cancelled: {
    color: '#f59e0b',
    bgColor: 'rgba(245, 158, 11, 0.1)',
    icon: <MinusCircleOutlined />,
    label: '已取消',
  },
};

interface TaskStatusTagProps {
  status: TaskStatus;
  size?: 'small' | 'default' | 'large';
  taskType?: string;
  showIcon?: boolean;
  showLabel?: boolean;
  customConfig?: Partial<TaskStatusConfig>;
  style?: React.CSSProperties;
  className?: string;
}

export const TaskStatusTag: React.FC<TaskStatusTagProps> = ({
  status,
  size = 'small',
  showIcon = true,
  showLabel = true,
  customConfig,
  style,
  className,
}) => {
  const config = { ...DEFAULT_STATUS_MAP[status], ...customConfig };

  const sizeStyles: Record<string, { fontSize: number; padding: string; borderRadius: number }> = {
    small: { fontSize: 12, padding: '2px 8px', borderRadius: 6 },
    default: { fontSize: 14, padding: '4px 12px', borderRadius: 8 },
    large: { fontSize: 16, padding: '6px 16px', borderRadius: 10 },
  };

  const sizeStyle = sizeStyles[size];

  return (
    <Tag
      className={className}
      style={{
        color: config.color,
        border: `1px solid ${config.color}44`,
        background: config.bgColor,
        fontSize: sizeStyle.fontSize,
        padding: sizeStyle.padding,
        borderRadius: sizeStyle.borderRadius,
        margin: 0,
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        ...style,
      }}
    >
      {showIcon && <span style={{ display: 'flex', alignItems: 'center' }}>{config.icon}</span>}
      {showLabel && <span>{config.label}</span>}
    </Tag>
  );
};

// 分析阶段标签
export const PHASE_LABELS: Record<string, string> = {
  init: '初始化',
  asr: '语音识别',
  emotion: '情绪分析',
  highlight: '高光识别',
  plot_parse: '解析剧情',
  narration_gen: '生成解说',
  tts: '语音合成',
  cutting: '剪辑原片',
  mixing: '音画合成',
  detect: '场景检测',
  score: '高光打分',
  select: '片段选择',
  sort: '智能排序',
  concat: '视频拼接',
  probe: '探测信息',
  transcode: '转码中',
  completed: '完成',
  failed: '失败',
  idle: '准备就绪',
  error: '错误',
  preparing: '准备中',
};

interface PhaseTagProps {
  phase: string;
  size?: 'small' | 'default' | 'large';
  showIcon?: boolean;
}

export const PhaseTag: React.FC<PhaseTagProps> = ({
  phase,
  size = 'small',
  showIcon = true,
}) => {
  const label = PHASE_LABELS[phase] || phase;
  const icon = <SyncOutlined style={{ fontSize: size === 'small' ? 10 : 12 }} />;

  return (
    <Tag
      style={{
        color: '#00d4ff',
        border: '1px solid rgba(0, 212, 255, 0.3)',
        background: 'rgba(0, 212, 255, 0.1)',
        fontSize: size === 'small' ? 12 : 14,
        padding: size === 'small' ? '2px 8px' : '4px 12px',
        borderRadius: 6,
        margin: 0,
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
      }}
    >
      {showIcon && icon}
      {label}
    </Tag>
  );
};

// 进度百分比标签
interface ProgressTagProps {
  progress: number;
  showPercent?: boolean;
  size?: 'small' | 'default';
}

export const ProgressTag: React.FC<ProgressTagProps> = ({
  progress,
  showPercent = true,
  size = 'small',
}) => {
  const getColor = () => {
    if (progress < 0) return '#ef4444';
    if (progress >= 100) return '#10b981';
    return '#00d4ff';
  };

  return (
    <Tag
      style={{
        color: getColor(),
        border: `1px solid ${getColor()}44`,
        background: `${getColor()}11`,
        fontSize: size === 'small' ? 12 : 14,
        padding: size === 'small' ? '2px 8px' : '4px 12px',
        borderRadius: 6,
        margin: 0,
      }}
    >
      {showPercent ? `${Math.round(progress)}%` : progress}
    </Tag>
  );
};

export default TaskStatusTag;
