/**
 * 页面：系统设置
 * 由各 Tab 子组件组装而成
 * 模型管理已分离到 /models 页面，这里只负责“用哪个引擎/参数”
 */

import React, { useEffect, useState, useCallback } from 'react';
import { Typography, Space, Button, message, Tabs, Alert, Card } from 'antd';
import { SaveOutlined, SettingOutlined, UndoOutlined, DatabaseOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { settingsApi, modelApi, systemApi } from '../services/ipc';
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
  const navigate = useNavigate();
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [hasChanges, setHasChanges] = useState(false);
  const [activeTab, setActiveTab] = useState('models-config');

  /* ---- 轻量模型状态（仅供 TTSTab/ASRTab 下拉选项，完整管理在 /models 页） ---- */
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [ttsBackends, setTtsBackends] = useState<any[]>([]);
  const [modelDownloads, setModelDownloads] = useState<
    Record<string, { progress: number; message: string }>
  >({});

  /* 加载模型列表（轻量版，仅用于引擎选择下拉框） */
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

  const loadTtsBackends = useCallback(async () => {
    try {
      const list = await systemApi.ttsBackends() as any[] || [];
      setTtsBackends(list);
    } catch {
      setTtsBackends([]);
    }
  }, []);

  /* 下载 / 删除：重定向到模型管理页 */
  const handleDownload = async (_modelId: string) => {
    message.info('请前往「模型管理」页面进行下载');
    navigate('/models');
  };

  const handleDelete = async (_modelId: string, _name: string) => {
    message.info('请前往「模型管理」页面进行删除');
    navigate('/models');
  };

  /* 首次加载 */
  useEffect(() => {
    loadModels();
    loadTtsBackends();
  }, [loadModels, loadTtsBackends]);

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
      key: 'models-config',
      label: <Space><SettingOutlined /><span>模型相关配置</span></Space>,
      children: (
        <div style={{ maxWidth: 800 }}>
          <Card title="Hugging Face 配置" style={{ marginBottom: 24 }}>
            <p>用于下载 gated 模型（pyannote 等）。建议在「模型管理」中进行完整下载与安装。</p>
            <Button 
              type="primary" 
              icon={<DatabaseOutlined />}
              onClick={() => navigate('/models')}
            >
              前往模型管理（下载 / 安装 / 健康监控）
            </Button>
          </Card>

          <Card title="默认引擎选择">
            <p>在这里选择默认使用的 TTS / ASR / Diarization 引擎。实际模型请到模型管理页安装。</p>
            {/* 这里可以保留原来的 TTS / ASR / Diarization 配置表单 */}
            <Text type="secondary">（详细引擎配置已移至独立的「模型管理」页面）</Text>
          </Card>
        </div>
      ),
    },
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
          ttsBackends={ttsBackends}  // 新：带 required_models 的引擎列表
          modelDownloads={modelDownloads}
          onDownload={handleDownload}
          onDelete={handleDelete}
          customModels={settings.custom_models}
          onCustomModelsChange={async (v) => {
            if (!settings) return;
            const newSettings: AppSettings = {
              ...settings,
              custom_models: {
                asr: v.asr ?? settings.custom_models?.asr ?? [],
                tts: v.tts ?? settings.custom_models?.tts ?? [],
              }
            };
            setSettings(newSettings);
            await settingsApi.update(newSettings);
            loadModels();
          }}
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
          customModels={settings.custom_models}
          onCustomModelsChange={async (v) => {
            if (!settings) return;
            const newSettings: AppSettings = {
              ...settings,
              custom_models: {
                asr: v.asr ?? settings.custom_models?.asr ?? [],
                tts: v.tts ?? settings.custom_models?.tts ?? [],
              }
            };
            setSettings(newSettings);
            await settingsApi.update(newSettings);
            loadModels();
          }}
          diarizationConfig={settings.diarization}
          onDiarizationChange={async (v) => {
            if (!settings) return;
            const newSettings: AppSettings = {
              ...settings,
              diarization: {
                ...settings.diarization,
                ...v,
                engine: v.engine ?? settings.diarization?.engine ?? 'clustering',
                use_pyannote_by_default: v.use_pyannote_by_default ?? (v.engine === 'pyannote'),
              }
            };
            setSettings(newSettings);
            await settingsApi.update(newSettings);
          }}
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
