/**
 * 页面：系统设置
 * 由各 Tab 子组件组装而成
 */

import React, { useEffect, useState, useCallback, useRef } from 'react';
import { Typography, Space, Button, message, Tabs, Modal, Alert } from 'antd';
import { SaveOutlined, SettingOutlined, UndoOutlined } from '@ant-design/icons';
import { settingsApi, modelApi, ipcClient, StorageInfo } from '../services/ipc';
import type { AppSettings, ModelInfo } from '../services/ipc';

import { AIModelsTab } from '../components/settings/AIModelsTab';
import { TTSTab } from '../components/settings/TTSTab';
import { ASRTab } from '../components/settings/ASRTab';
import { ViTTab } from '../components/settings/ViTTab';
import { OutputTab } from '../components/settings/OutputTab';
import { HardwareTab } from '../components/settings/HardwareTab';
import { StorageManagementTab } from '../components/settings/StorageManagementTab';

const { Title, Text } = Typography;

/* ====== SettingsPage 主组件 ====== */
const SettingsPage: React.FC = () => {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [hasChanges, setHasChanges] = useState(false);
  const [activeTab, setActiveTab] = useState('models');

  /* ---- 模型管理状态 ---- */
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelDownloads, setModelDownloads] = useState<
    Record<string, { progress: number; message: string }>
  >({});
  const modelPollRef = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  /* 加载模型列表 */
  const loadModels = useCallback(async () => {
    try {
      const list = await modelApi.list();
      setModels(list);
    } catch {
      // Dev fallback - 模拟数据
      setModels([
        { id: 'whisper-tiny', name: 'Whisper Tiny', category: 'asr', type: 'whisper', size_mb: 150, description: '轻量级，速度快', downloaded: false, disk_size_bytes: 0 },
        { id: 'whisper-base', name: 'Whisper Base', category: 'asr', type: 'whisper', size_mb: 290, description: '基础模型', downloaded: true, disk_size_bytes: 300_000_000 },
        { id: 'whisper-small', name: 'Whisper Small', category: 'asr', type: 'whisper', size_mb: 950, description: '中等大小', downloaded: false, disk_size_bytes: 0 },
        { id: 'whisper-medium', name: 'Whisper Medium', category: 'asr', type: 'whisper', size_mb: 3000, description: '大模型', downloaded: false, disk_size_bytes: 0 },
        { id: 'whisper-large-v3', name: 'Whisper Large V3', category: 'asr', type: 'whisper', size_mb: 6000, description: '最大模型', downloaded: false, disk_size_bytes: 0 },
        { id: 'styletts2', name: 'StyleTTS 2', category: 'tts', type: 'styletts2', size_mb: 2000, description: '情感语音合成', downloaded: false, disk_size_bytes: 0 },
      ]);
    }
  }, []);

  /* 轮询下载进度 */
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
      } catch {
        // ignore
      }
    }, 2000);
  }, [loadModels]);

  /* 监听进度通知（通过 IPC） */
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

  /* 下载模型 */
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

  /* 删除模型 */
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

  /* 首次加载 */
  useEffect(() => {
    loadModels();
  }, [loadModels]);

  /* 加载设置 */
  useEffect(() => {
    (async () => {
      try {
        const data = await settingsApi.get();
        setSettings(data);
      } catch (err) {
        message.error('加载设置失败');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  /* 通用更新函数 */
  const updateSetting = useCallback(
    <K extends keyof AppSettings>(section: K, value: Partial<AppSettings[K]>) => {
      setSettings((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          [section]:
            typeof value === 'object' && !Array.isArray(value)
              ? { ...prev[section], ...value }
              : value,
        };
      });
      setHasChanges(true);
    },
    [],
  );

  /* 提供商 config 更新 */
  const updateProvider = useCallback(
    (key: string, patch: Partial<AppSettings['openai_protocol']>) => {
      setSettings((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          [key]: { ...(prev as any)[key], ...patch },
        };
      });
      setHasChanges(true);
    },
    [],
  );

  /* 保存 */
  const handleSave = async () => {
    if (!settings) return;
    setSaving(true);
    try {
      await settingsApi.update(settings);
      message.success('设置已保存');
      setHasChanges(false);
    } catch (err) {
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  /* 重置 */
  const handleReset = () => {
    setLoading(true);
    settingsApi.get().then((data) => {
      setSettings(data);
      setHasChanges(false);
      setLoading(false);
      message.info('已重置为已保存的配置');
    });
  };

  if (loading || !settings) {
    return (
      <div style={{ padding: 24, textAlign: 'center' }}>
        <Text type="secondary">加载配置中...</Text>
      </div>
    );
  }

  const tabs = [
    {
      key: 'models',
      label: <Space><SettingOutlined /><span>AI 模型</span></Space>,
      children: (
        <AIModelsTab
          openaiConfig={settings.openai_protocol}
          anthropicConfig={settings.anthropic_protocol}
          onChange={updateProvider}
        />
      ),
    },
    {
      key: 'tts',
      label: <Space><span>语音合成 (TTS)</span></Space>,
      children: (
        <TTSTab
          ttsConfig={settings.tts}
          onTTSChange={(v) => updateSetting('tts', v)}
          models={models}
          modelDownloads={modelDownloads}
          onDownload={handleDownload}
          onDelete={handleDelete}
        />
      ),
    },
    {
      key: 'asr',
      label: <Space><span>语音识别 (ASR)</span></Space>,
      children: (
        <ASRTab
          asrConfig={settings.asr}
          onASRChange={(v) => updateSetting('asr', v)}
          models={models}
          modelDownloads={modelDownloads}
          onDownload={handleDownload}
          onDelete={handleDelete}
        />
      ),
    },
    {
      key: 'vit',
      label: <Space><span>视觉分析 (ViT)</span></Space>,
      children: (
        <ViTTab
          vitConfig={settings.vit}
          onViTChange={(v) => updateSetting('vit', v)}
        />
      ),
    },
    {
      key: 'output',
      label: <Space><span>输出参数</span></Space>,
      children: (
        <OutputTab
          outputConfig={settings.output}
          onOutputChange={(v) => updateSetting('output', v)}
        />
      ),
    },
    {
      key: 'hardware',
      label: <Space><span>硬件加速</span></Space>,
      children: (
        <HardwareTab
          hardwareConfig={settings.hardware}
          onHardwareChange={(v) => updateSetting('hardware', v)}
        />
      ),
    },
    {
      key: 'storage',
      label: <Space><span>存储管理</span></Space>,
      children: <StorageManagementTab outputsDir={settings.output.path} />,
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      {/* 页面标题 */}
      <div
        style={{
          marginBottom: 24,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <div>
          <Title level={2} style={{ margin: 0, color: '#e0e6f0' }}>
            <SettingOutlined style={{ marginRight: 8, color: '#00d4ff' }} />
            系统设置
          </Title>
          <Text type="secondary" style={{ marginTop: 4, display: 'block' }}>
            配置 AI 模型、输出参数、语音合成与硬件加速
          </Text>
        </div>
        <Space>
          <Button icon={<UndoOutlined />} onClick={handleReset} disabled={!hasChanges}>
            重置
          </Button>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            onClick={handleSave}
            loading={saving}
            disabled={!hasChanges}
            style={{
              background: hasChanges ? 'linear-gradient(135deg, #00d4ff 0%, #722ed1 100%)' : undefined,
              borderColor: hasChanges ? 'transparent' : undefined,
              boxShadow: hasChanges ? '0 0 12px rgba(0, 212, 255, 0.4)' : undefined,
              textShadow: hasChanges ? '0 1px 2px rgba(0, 0, 0, 0.4)' : undefined,
              transition: 'all 0.3s ease',
            }}
          >
            保存配置
          </Button>
        </Space>
      </div>

      {/* 未保存修改提醒条 */}
      {hasChanges && (
        <Alert
          message="检测到您已修改了配置参数，请及时点击右上角的「保存配置」按钮，以使您的全新设置生效。"
          type="warning"
          showIcon
          style={{
            marginBottom: 20,
            background: '#faad1411',
            borderColor: '#faad1433',
            color: '#faad14',
            borderRadius: 6,
          }}
        />
      )}

      {/* 主标签页 */}
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        type="card"
        style={{ color: '#e0e6f0' }}
        tabBarStyle={{ marginBottom: 16 }}
        items={tabs}
      />
    </div>
  );
};

export default SettingsPage;
