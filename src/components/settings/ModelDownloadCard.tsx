/**
 * Premium Model Status Card and Grid
 */

import React, { useState } from 'react';
import { Card, Tag, Progress, Button, Typography, Space, Tooltip, message, Popconfirm } from 'antd';
import {
  CheckCircleFilled,
  CloudDownloadOutlined,
  DeleteOutlined,
  CopyOutlined,
  FolderOpenOutlined,
  SlidersOutlined,
  CompassOutlined,
  ExclamationCircleOutlined,
  LoadingOutlined,
} from '@ant-design/icons';

const { Text, Paragraph } = Typography;

export interface ModelInfo {
  id: string;
  name: string;
  category: 'asr' | 'tts' | 'diarization';
  type: 'whisper' | 'styletts2' | 'supertonic' | 'sensevoice' | 'pyannote' | 'custom';
  size_mb: number;
  description: string;
  downloaded: boolean;
  disk_size_bytes: number;
  flat_path?: string;
  source_id?: string;
  scenarios?: string;
}

export interface ModelStatusRowProps {
  model: ModelInfo;
  downloadInfo?: { progress: number; message: string };
  onDownload: (modelId: string) => void;
  onDelete: (modelId: string, modelName: string) => void;
}

export const ModelStatusRow: React.FC<ModelStatusRowProps> = ({
  model,
  downloadInfo,
  onDownload,
  onDelete,
}) => {
  const downloading = downloadInfo !== undefined;
  const failed = downloading && (downloadInfo?.progress ?? 0) < 0;
  const progressVal = downloading ? Math.max(0, Math.min(100, downloadInfo?.progress ?? 0)) : 0;

  const [hovered, setHovered] = useState(false);

  // Copy helper
  const handleCopy = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    message.success(`${label}已复制到剪贴板`);
  };

  // Humanize size
  const formatSize = (mb: number) => {
    if (mb >= 1000) {
      return `${(mb / 1000).toFixed(2)} GB`;
    }
    return `${mb} MB`;
  };

  // Status Styling HSL
  let statusTag = null;
  let statusCardStyle: React.CSSProperties = {};

  if (model.downloaded) {
    statusTag = (
      <Tag
        icon={<CheckCircleFilled style={{ color: '#10b981' }} />}
        style={{
          background: 'rgba(16, 185, 129, 0.15)',
          border: '1px solid rgba(16, 185, 129, 0.3)',
          color: '#10b981',
          borderRadius: '4px',
          fontWeight: 600,
        }}
      >
        已就绪
      </Tag>
    );
    statusCardStyle = {
      boxShadow: hovered ? '0 8px 30px rgba(16, 185, 129, 0.08)' : 'none',
      borderColor: hovered ? 'rgba(16, 185, 129, 0.3)' : 'rgba(255, 255, 255, 0.08)',
    };
  } else if (downloading) {
    statusTag = (
      <Tag
        icon={failed ? <ExclamationCircleOutlined /> : <LoadingOutlined spin />}
        style={{
          background: failed ? 'rgba(239, 68, 68, 0.15)' : 'rgba(59, 130, 246, 0.15)',
          border: failed ? '1px solid rgba(239, 68, 68, 0.3)' : '1px solid rgba(59, 130, 246, 0.3)',
          color: failed ? '#ef4444' : '#3b82f6',
          borderRadius: '4px',
          fontWeight: 600,
        }}
      >
        {failed ? '下载失败' : '正在下载'}
      </Tag>
    );
    statusCardStyle = {
      boxShadow: '0 8px 30px rgba(59, 130, 246, 0.12)',
      borderColor: failed ? 'rgba(239, 68, 68, 0.4)' : 'rgba(59, 130, 246, 0.5)',
    };
  } else {
    statusTag = (
      <Tag
        style={{
          background: 'rgba(255, 255, 255, 0.05)',
          border: '1px solid rgba(255, 255, 255, 0.15)',
          color: '#a1a1aa',
          borderRadius: '4px',
          fontWeight: 500,
        }}
      >
        未下载 (本地缺失)
      </Tag>
    );
    statusCardStyle = {
      boxShadow: hovered ? '0 8px 30px rgba(255, 255, 255, 0.04)' : 'none',
      borderColor: hovered ? 'rgba(255, 255, 255, 0.2)' : 'rgba(255, 255, 255, 0.08)',
    };
  }

  return (
    <Card
      style={{
        background: 'rgba(24, 24, 37, 0.65)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        borderRadius: '12px',
        transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
        overflow: 'hidden',
        borderWidth: '1px',
        borderStyle: 'solid',
        ...statusCardStyle,
      }}
      bodyStyle={{ padding: '16px' }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
        
        {/* Header Block */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Space size={8}>
            <SlidersOutlined style={{ color: '#818cf8', fontSize: '16px' }} />
            <Text style={{ fontSize: '16px', fontWeight: 700, color: '#f4f4f5' }}>
              {model.name}
            </Text>
            <Tag color={model.category === 'asr' ? 'purple' : 'cyan'} style={{ borderRadius: '4px' }}>
              {model.category.toUpperCase()}
            </Tag>
          </Space>
          {statusTag}
        </div>

        {/* 5-Properties Content Grid */}
        <div style={{ 
          display: 'grid', 
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', 
          gap: '12px',
          background: 'rgba(255, 255, 255, 0.02)',
          padding: '12px',
          borderRadius: '8px',
          border: '1px solid rgba(255, 255, 255, 0.04)'
        }}>
          {/* Prop 1: Source / ID */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <span style={{ fontSize: '11px', color: '#71717a', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              来源渠道 / ID
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ 
                fontFamily: 'monospace', 
                fontSize: '12px', 
                color: '#e4e4e7',
                background: 'rgba(255, 255, 255, 0.05)',
                padding: '2px 6px',
                borderRadius: '4px',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                maxWidth: '240px'
              }}>
                {model.source_id || 'N/A'}
              </span>
              {model.source_id && (
                <Tooltip title="复制 ID">
                  <Button 
                    type="text" 
                    size="small" 
                    icon={<CopyOutlined style={{ fontSize: '12px', color: '#a1a1aa' }} />} 
                    onClick={() => handleCopy(model.source_id || '', '来源 ID')}
                    style={{ padding: 0, width: '20px', height: '20px' }}
                  />
                </Tooltip>
              )}
            </div>
          </div>

          {/* Prop 2: Flat Path */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <span style={{ fontSize: '11px', color: '#71717a', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              推荐绝对路径 (平铺直读)
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ 
                fontFamily: 'monospace', 
                fontSize: '12px', 
                color: '#34d399',
                background: 'rgba(52, 211, 153, 0.05)',
                padding: '2px 6px',
                borderRadius: '4px',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                maxWidth: '300px'
              }} title={model.flat_path}>
                {model.flat_path || 'N/A'}
              </span>
              {model.flat_path && (
                <Tooltip title="复制安装路径">
                  <Button 
                    type="text" 
                    size="small" 
                    icon={<CopyOutlined style={{ fontSize: '12px', color: '#a1a1aa' }} />} 
                    onClick={() => handleCopy(model.flat_path || '', '绝对安装路径')}
                    style={{ padding: 0, width: '20px', height: '20px' }}
                  />
                </Tooltip>
              )}
            </div>
          </div>

          {/* Prop 3: Est Size */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <span style={{ fontSize: '11px', color: '#71717a', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              预估体积 / 实际大小
            </span>
            <span style={{ fontSize: '13px', fontWeight: 600, color: '#f4f4f5' }}>
              {formatSize(model.size_mb)}
              {model.downloaded && model.disk_size_bytes > 0 && (
                <span style={{ fontSize: '11px', color: '#71717a', fontWeight: 400, marginLeft: '6px' }}>
                  (已占用: {(model.disk_size_bytes / (1024 * 1024)).toFixed(1)} MB)
                </span>
              )}
            </span>
          </div>

          {/* Prop 4: Scenarios */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', gridColumn: 'span 2' }}>
            <span style={{ fontSize: '11px', color: '#71717a', textTransform: 'uppercase', letterSpacing: '0.5px', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <CompassOutlined /> 功能定位与适用场景
            </span>
            <span style={{ fontSize: '12px', color: '#d4d4d8', lineHeight: 1.4 }}>
              {model.scenarios || model.description}
            </span>
          </div>
        </div>

        {/* Download Progress Bar */}
        {downloading && (
          <div style={{ 
            background: 'rgba(255, 255, 255, 0.02)', 
            padding: '10px 14px', 
            borderRadius: '8px', 
            border: '1px solid rgba(255, 255, 255, 0.04)' 
          }}>
            <Progress
              percent={progressVal}
              status={failed ? 'exception' : 'active'}
              size="small"
              strokeColor={{
                '0%': '#3b82f6',
                '100%': '#6366f1',
              }}
              format={() => (
                <span style={{ color: failed ? '#ef4444' : '#e4e4e7', fontSize: '12px', fontWeight: 500 }}>
                  {downloadInfo?.message || `${progressVal}%`}
                </span>
              )}
            />
          </div>
        )}

        {/* Footer Actions */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '4px' }}>
          {model.downloaded ? (
            <Popconfirm
              title={`确定要删除模型权重吗？`}
              description={
                <div>
                  <p>这将释放 {formatSize(model.size_mb)} 空间。</p>
                  {model.type === 'custom' && <p style={{ color: '#eab308' }}>注意: 自定义导入模型将只解除配置注册，不会删除用户原物理路径中的文件。</p>}
                </div>
              }
              onConfirm={() => onDelete(model.id, model.name)}
              okText="确认删除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
            >
              <Button
                danger
                ghost
                size="middle"
                icon={<DeleteOutlined />}
                style={{ borderRadius: '6px' }}
              >
                删除权重
              </Button>
            </Popconfirm>
          ) : (
            <Button
              type="primary"
              size="middle"
              icon={<CloudDownloadOutlined />}
              loading={downloading && !failed}
              disabled={downloading && !failed}
              onClick={() => onDownload(model.id)}
              style={{ 
                borderRadius: '6px',
                background: failed ? '#ef4444' : 'linear-gradient(135deg, #4f46e5 0%, #3b82f6 100%)',
                borderColor: 'transparent',
                boxShadow: '0 4px 14px rgba(79, 70, 229, 0.3)',
              }}
            >
              {failed ? '重试下载' : '立即部署'}
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
};
