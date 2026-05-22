/**
 * 模型状态/下载行
 */

import React from 'react';
import { Row, Col, Button, Space, Tag, Progress, Typography } from 'antd';
import {
  CheckCircleOutlined,
  CloudDownloadOutlined,
  InfoCircleOutlined,
  DeleteOutlined,
} from '@ant-design/icons';

const { Text } = Typography;

export interface ModelInfo {
  id: string;
  name: string;
  category: string;
  type: string;
  size_mb: number;
  description: string;
  downloaded: boolean;
  disk_size_bytes: number;
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
  const activeDownload = downloading && (downloadInfo?.progress ?? 0) >= 0;
  const failed = downloading && (downloadInfo?.progress ?? 0) < 0;

  return (
    <Row gutter={16} align="middle">
      <Col flex="auto">
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          <Space>
            <Text strong>{model.name}</Text>
            {model.downloaded ? (
              <Tag color="success" icon={<CheckCircleOutlined />}>已下载</Tag>
            ) : downloading ? (
              <Tag color="processing" icon={<CloudDownloadOutlined spin />}>
                {failed ? '失败' : '下载中'}
              </Tag>
            ) : (
              <Tag icon={<InfoCircleOutlined />}>未下载</Tag>
            )}
            <Text type="secondary" style={{ fontSize: 12 }}>
              {model.description} · {model.size_mb >= 1000 ? `${(model.size_mb / 1000).toFixed(1)} GB` : `${model.size_mb} MB`}
            </Text>
          </Space>
          {downloading && (
            <Progress
              percent={Math.round(downloadInfo?.progress ?? 0)}
              status={failed ? 'exception' : 'active'}
              size="small"
              format={() => downloadInfo?.message ?? ''}
            />
          )}
        </Space>
      </Col>
      <Col>
        {model.downloaded ? (
          <Button
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() => onDelete(model.id, model.name)}
          >
            删除
          </Button>
        ) : (
          <Button
            size="small"
            type="primary"
            icon={<CloudDownloadOutlined />}
            loading={downloading && !failed}
            disabled={downloading && !failed}
            onClick={() => onDownload(model.id)}
          >
            {failed ? '重试' : '下载'}
          </Button>
        )}
      </Col>
    </Row>
  );
};
