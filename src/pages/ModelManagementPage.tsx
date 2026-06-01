/**
 * 模型管理页面 - 一级功能区
 * 
 * 职责：模型发现、下载、安装运行时、健康监控、删除管理
 * 与「系统设置」分离：设置只负责“用哪个引擎/参数”，这里负责“把引擎装好”
 */
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { Typography, Divider, Button, Space, Tabs, message, Modal } from 'antd';
import {
  DatabaseOutlined,
  ArrowLeftOutlined,
  SettingOutlined,
  HeartOutlined,
  CloudDownloadOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { modelApi, ipcClient } from '../services/ipc';
import type { ModelInfo } from '../services/ipc';
import { QualityEnginesPanel } from '../components/settings/QualityEnginesPanel';
import { CentralModelsTab } from '../components/settings/CentralModelsTab';

const { Title, Text } = Typography;

const ModelManagementPage: React.FC = () => {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState('overview');

  /* ── 模型列表状态 ── */
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelDownloads, setModelDownloads] = useState<
    Record<string, { progress: number; message: string }>
  >({});
  const modelPollRef = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  /* ── 加载模型列表 ── */
  const loadModels = useCallback(async () => {
    try {
      const res = await modelApi.list() as any;
      let list: any[] = [];
      if (res && Array.isArray(res)) {
        list = res;
      } else if (res) {
        list = [...(res.legacy || []), ...(res.central_catalog || [])];
      }
      const seen = new Set();
      list = list.filter((m: any) => {
        const key = m.id || m.repo_id || m.name;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
      setModels(list);
    } catch {
      setModels([]);
    }
  }, []);

  /* ── 轮询下载进度 ── */
  const pollDownload = useCallback((modelId: string) => {
    if (modelPollRef.current[modelId]) {
      clearInterval(modelPollRef.current[modelId]);
    }
    modelPollRef.current[modelId] = setInterval(async () => {
      try {
        const status = await modelApi.status(modelId);
        if (!status.downloading) {
          clearInterval(modelPollRef.current[modelId]);
          delete modelPollRef.current[modelId];
          loadModels();
          setModelDownloads((prev) => {
            const next = { ...prev };
            delete next[modelId];
            return next;
          });
        }
      } catch { /* ignore */ }
    }, 2000);
  }, [loadModels]);

  /* ── IPC 进度监听 ── */
  useEffect(() => {
    const unsub = ipcClient.onProgress((payload) => {
      if (payload?.phase === 'download' && payload?.task_id) {
        setModelDownloads((prev) => ({
          ...prev,
          [payload.task_id]: {
            progress: payload.progress,
            message: (payload as any).message || '',
          },
        }));
      }
    });
    return unsub;
  }, []);

  /* ── 组件卸载时清理所有轮询 ── */
  useEffect(() => {
    return () => {
      Object.values(modelPollRef.current).forEach(clearInterval);
    };
  }, []);

  /* ── 首次加载 ── */
  useEffect(() => {
    loadModels();
  }, [loadModels]);

  /* ── 下载 ── */
  const handleDownload = async (modelId: string) => {
    try {
      setModelDownloads((prev) => ({ ...prev, [modelId]: { progress: 0, message: '正在启动…' } }));
      await modelApi.download(modelId);
      pollDownload(modelId);
    } catch {
      setModelDownloads((prev) => ({ ...prev, [modelId]: { progress: -1, message: '启动失败' } }));
      message.error('启动下载失败');
    }
  };

  /* ── 删除 ── */
  const handleDelete = async (modelId: string, name: string) => {
    Modal.confirm({
      title: `确认删除 ${name}？`,
      content: '删除后如需使用需重新下载。',
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await modelApi.delete(modelId);
          message.success(`${name} 已删除`);
          loadModels();
        } catch {
          message.error('删除失败');
        }
      },
    });
  };

  /* ── 统计信息 ── */
  const installedCount = models.filter((m) => m.downloaded).length;
  const downloadingCount = Object.keys(modelDownloads).length;

  const tabItems = [
    {
      key: 'overview',
      label: (
        <Space>
          <HeartOutlined />
          <span>引擎总览</span>
        </Space>
      ),
      children: (
        <div>
          <QualityEnginesPanel />
          <Divider />
          {/* 模型统计卡片 */}
          <div style={{ display: 'flex', gap: 16, marginBottom: 16 }}>
            <div style={{
              flex: 1, padding: '16px 20px', borderRadius: 8,
              background: 'rgba(0, 212, 255, 0.06)', border: '1px solid rgba(0, 212, 255, 0.15)',
            }}>
              <Text type="secondary" style={{ fontSize: 12 }}>已安装模型</Text>
              <div style={{ fontSize: 28, fontWeight: 700, color: '#00d4ff' }}>{installedCount}</div>
            </div>
            <div style={{
              flex: 1, padding: '16px 20px', borderRadius: 8,
              background: 'rgba(124, 58, 237, 0.06)', border: '1px solid rgba(124, 58, 237, 0.15)',
            }}>
              <Text type="secondary" style={{ fontSize: 12 }}>下载中</Text>
              <div style={{ fontSize: 28, fontWeight: 700, color: '#7c3aed' }}>{downloadingCount}</div>
            </div>
            <div style={{
              flex: 1, padding: '16px 20px', borderRadius: 8,
              background: 'rgba(16, 185, 129, 0.06)', border: '1px solid rgba(16, 185, 129, 0.15)',
            }}>
              <Text type="secondary" style={{ fontSize: 12 }}>模型总数</Text>
              <div style={{ fontSize: 28, fontWeight: 700, color: '#10b981' }}>{models.length}</div>
            </div>
          </div>
        </div>
      ),
    },
    {
      key: 'central',
      label: (
        <Space>
          <CloudDownloadOutlined />
          <span>模型目录与下载</span>
        </Space>
      ),
      children: (
        <CentralModelsTab
          modelDownloads={modelDownloads}
          onRefresh={loadModels}
        />
      ),
    },
  ];

  return (
    <div style={{ padding: '24px 32px', maxWidth: 1200, margin: '0 auto' }}>
      {/* 页面头部 */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 24,
      }}>
        <div>
          <Title level={2} style={{ margin: 0, color: '#e0e6f0' }}>
            <DatabaseOutlined style={{ marginRight: 8, color: '#7c3aed' }} />
            模型管理
          </Title>
          <Text type="secondary" style={{ marginTop: 4, display: 'block' }}>
            发现、下载、安装和管理所有高质量本地 AI 模型。安装完成后即可在「系统设置」中选择使用。
          </Text>
        </div>
        <Space>
          <Button
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/')}
          >
            返回首页
          </Button>
          <Button
            icon={<SettingOutlined />}
            onClick={() => navigate('/settings')}
          >
            系统设置
          </Button>
        </Space>
      </div>

      {/* 主标签页 */}
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        type="card"
        items={tabItems}
        style={{ color: '#e0e6f0' }}
        tabBarStyle={{ marginBottom: 16 }}
      />
    </div>
  );
};

export default ModelManagementPage;
