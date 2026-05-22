/**
 * 存储管理 Tab
 */

import React, { useEffect, useState, useCallback } from 'react';
import { Card, Row, Col, Space, Button, Table, Tag, Empty, Modal, Typography, Statistic, Divider } from 'antd';

const { Text } = Typography;
import {
  FolderOpenOutlined,
  DatabaseOutlined,
  ClockCircleOutlined,
  ClearOutlined,
  DeleteOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons';
import { systemApi, StorageInfo } from '../../services/ipc';
import { useOutputHistoryStore, formatFileSize, formatDuration } from '../../stores/outputHistoryStore';

function formatFileSizeLocal(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
}

function formatDurationLocal(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

interface StorageManagementTabProps {
  outputsDir?: string;
}

export const StorageManagementTab: React.FC<StorageManagementTabProps> = ({ outputsDir }) => {
  const [loading, setLoading] = useState(true);
  const [storageInfo, setStorageInfo] = useState<StorageInfo | null>(null);
  const { records, clearHistory, removeRecord } = useOutputHistoryStore();

  const loadStorageInfo = useCallback(async () => {
    setLoading(true);
    try {
      const info = await systemApi.getStorageInfo();
      setStorageInfo(info);
    } catch {
      setStorageInfo({
        outputsDir: outputsDir || '/tmp',
        outputsCount: records.length,
        outputsSize: records.reduce((sum, r) => sum + r.fileSize, 0),
        cacheSize: 0,
        tempSize: 0,
        totalSize: records.reduce((sum, r) => sum + r.fileSize, 0),
      });
    } finally {
      setLoading(false);
    }
  }, [records, outputsDir]);

  useEffect(() => {
    loadStorageInfo();
  }, [loadStorageInfo]);

  const handleOpenOutputsDir = () => {
    if (storageInfo?.outputsDir) {
      window.open(`file://${storageInfo.outputsDir}`);
    }
  };

  const handleClearHistory = () => {
    Modal.confirm({
      title: '确认清空历史记录？',
      content: '这只会清空历史记录列表，不会删除实际文件。',
      okText: '确认清空',
      okType: 'danger',
      cancelText: '取消',
      onOk: () => {
        clearHistory();
        loadStorageInfo();
      },
    });
  };

  const handleDeleteRecord = (id: string) => {
    Modal.confirm({
      title: '确认删除记录？',
      content: '这只会从历史记录中移除，不会删除实际文件。',
      okText: '确认删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: () => {
        removeRecord(id);
        loadStorageInfo();
      },
    });
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 40 }}>
        <Text type="secondary">加载存储信息中...</Text>
      </div>
    );
  }

  const totalSize = storageInfo?.totalSize ?? 0;
  const outputsSize = storageInfo?.outputsSize ?? 0;
  const cacheSize = storageInfo?.cacheSize ?? 0;
  const tempSize = storageInfo?.tempSize ?? 0;

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={16}>
      <Card size="small" style={{ borderColor: '#00d4ff44' }}>
        <Row gutter={16}>
          <Col span={6}>
            <Statistic
              title="输出文件"
              value={storageInfo?.outputsCount ?? 0}
              suffix="个"
              prefix={<FolderOpenOutlined />}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="输出大小"
              value={outputsSize / (1024 * 1024 * 1024)}
              precision={2}
              suffix="GB"
              prefix={<DatabaseOutlined />}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="缓存大小"
              value={cacheSize / (1024 * 1024 * 1024)}
              precision={2}
              suffix="GB"
              prefix={<DatabaseOutlined />}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="临时文件"
              value={tempSize / (1024 * 1024 * 1024)}
              precision={2}
              suffix="GB"
              prefix={<ClockCircleOutlined />}
            />
          </Col>
        </Row>
        <Divider style={{ margin: '12px 0' }} />
        <Row align="middle" gutter={16}>
          <Col flex="auto">
            <Space>
              <Text type="secondary">输出目录：</Text>
              <Text code style={{ fontSize: 12 }}>{storageInfo?.outputsDir}</Text>
            </Space>
          </Col>
          <Col>
            <Button icon={<FolderOpenOutlined />} onClick={handleOpenOutputsDir} size="small">
              打开目录
            </Button>
          </Col>
        </Row>
      </Card>

      <Card
        size="small"
        title={
          <Space>
            <ClockCircleOutlined />
            <span>历史输出记录</span>
            <Tag color="blue">{records.length} 条</Tag>
          </Space>
        }
        extra={
          <Space>
            <Button
              icon={<ClearOutlined />}
              danger
              size="small"
              onClick={handleClearHistory}
              disabled={records.length === 0}
            >
              清空记录
            </Button>
          </Space>
        }
        style={{ borderColor: '#722ed144' }}
      >
        {records.length === 0 ? (
          <Empty description="暂无历史输出记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <Table
            size="small"
            dataSource={records.slice(0, 20)}
            rowKey="id"
            pagination={false}
            columns={[
              {
                title: '文件',
                dataIndex: 'fileName',
                key: 'fileName',
                render: (name: string, record: any) => (
                  <Space>
                    <VideoCameraOutlined style={{ color: '#00d4ff' }} />
                    <Text>{name}</Text>
                  </Space>
                ),
              },
              {
                title: '大小',
                dataIndex: 'fileSize',
                key: 'fileSize',
                width: 100,
                render: (v: number) => <Text type="secondary">{formatFileSizeLocal(v)}</Text>,
              },
              {
                title: '时长',
                dataIndex: 'duration',
                key: 'duration',
                width: 100,
                render: (v: number) => <Text type="secondary">{formatDurationLocal(v)}</Text>,
              },
              {
                title: '参数',
                key: 'params',
                width: 150,
                render: (_: any, record: any) => (
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {record.quality} · {record.format}
                  </Text>
                ),
              },
              {
                title: '操作',
                key: 'action',
                width: 80,
                render: (_: any, record: any) => (
                  <Button
                    type="text"
                    danger
                    size="small"
                    icon={<DeleteOutlined />}
                    onClick={() => handleDeleteRecord(record.id)}
                  />
                ),
              },
            ]}
          />
        )}
      </Card>
    </Space>
  );
};
