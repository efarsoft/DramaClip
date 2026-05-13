/**
 * 页面：系统设置
 * AI 模型提供者、TTS、ASR、ViT、输出参数、硬件加速等完整配置
 */

import React, { useEffect, useState, useCallback } from 'react';
import {
  Card,
  Typography,
  Form,
  Input,
  InputNumber,
  Button,
  Switch,
  Select,
  Divider,
  Space,
  message,
  Tabs,
  Tooltip,
  Row,
  Col,
  Collapse,
} from 'antd';
import {
  SaveOutlined,
  UndoOutlined,
  ApiOutlined,
  AudioOutlined,
  EyeOutlined,
  TranslationOutlined,
  SettingOutlined,
  ThunderboltOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons';
import { settingsApi } from '../services/ipc';
import type { AppSettings } from '../services/ipc';

const { Title, Text } = Typography;

/* ---------- 协议模型选项 ---------- */
const MODEL_OPTIONS: Record<string, { label: string; value: string }[]> = {
  openai_protocol: [
    { label: 'GPT-4o', value: 'gpt-4o' },
    { label: 'GPT-4o-mini', value: 'gpt-4o-mini' },
    { label: 'GPT-4-turbo', value: 'gpt-4-turbo' },
    { label: 'o1', value: 'o1' },
    { label: 'o1-mini', value: 'o1-mini' },
    { label: 'o3-mini', value: 'o3-mini' },
    { label: 'DeepSeek Chat', value: 'deepseek-chat' },
    { label: 'DeepSeek Reasoner', value: 'deepseek-reasoner' },
    { label: 'Qwen Max', value: 'qwen-max' },
    { label: 'Qwen Plus', value: 'qwen-plus' },
    { label: 'Qwen Turbo', value: 'qwen-turbo' },
    { label: 'Moonshot v1 Auto', value: 'moonshot-v1-auto' },
    { label: 'Moonshot v1 128K', value: 'moonshot-v1-128k' },
    { label: 'Moonshot v1 32K', value: 'moonshot-v1-32k' },
    { label: 'Kimi (moonshot-v1)', value: 'moonshot-v1-8k' },
  ],
  anthropic_protocol: [
    { label: 'Claude 3.5 Sonnet', value: 'claude-3-5-sonnet-latest' },
    { label: 'Claude 3.5 Haiku', value: 'claude-3-5-haiku-latest' },
    { label: 'Claude 3 Opus', value: 'claude-3-opus-latest' },
  ],
};

/* ---------- 协议信息 ---------- */
const PROTOCOL_META: Record<
  string,
  { name: string; icon: string; desc: string; placeholder: string; docUrl?: string; compatibleList: string }
> = {
  openai_protocol: {
    name: 'OpenAI 兼容协议',
    icon: '',
    desc: '兼容所有 OpenAI API 格式的服务商，包括 OpenAI、DeepSeek、通义千问（Qwen）、Kimi (Moonshot)、Groq、Together AI 等',
    placeholder: 'sk-... 或对应 API Key',
    docUrl: 'https://platform.openai.com/api-keys',
    compatibleList: 'OpenAI, DeepSeek, 通义千问, Kimi, Groq, Together AI, ...',
  },
  anthropic_protocol: {
    name: 'Anthropic 兼容协议',
    icon: '',
    desc: '兼容 Anthropic Claude API 格式的服务商（Claude 3.5 / 3 系列模型）',
    placeholder: 'sk-ant-...',
    docUrl: 'https://console.anthropic.com/',
    compatibleList: 'Anthropic Claude',
  },
};

/* ====== 子组件：单个模型提供商卡片 ====== */
interface ModelProviderCardProps {
  providerKey: string;
  config: AppSettings['openai_protocol'];
  onChange: (key: string, value: Partial<AppSettings['openai_protocol']>) => void;
}

const ModelProviderCard: React.FC<ModelProviderCardProps> = ({
  providerKey,
  config,
  onChange,
}) => {
  const meta = PROTOCOL_META[providerKey];
  const models = MODEL_OPTIONS[providerKey] || [];

  return (
    <Card
      size="small"
      style={{
        marginBottom: 12,
        borderColor: config.enabled ? '#00d4ff44' : '#1e2540',
        opacity: config.enabled ? 1 : 0.65,
      }}
      title={
        <Space>
          <ApiOutlined style={{ color: config.enabled ? '#00d4ff' : '#6b7b9d' }} />
          <Text strong style={{ color: '#e0e6f0' }}>
            {meta.name}
          </Text>
          {config.enabled ? (
            <CheckCircleOutlined style={{ color: '#10b981', fontSize: 14 }} />
          ) : (
            <CloseCircleOutlined style={{ color: '#6b7b9d', fontSize: 14 }} />
          )}
        </Space>
      }
      extra={
        <Space>
          <Text type="secondary" style={{ fontSize: 12 }}>
            启用
          </Text>
          <Switch
            size="small"
            checked={config.enabled}
            onChange={(v) => onChange(providerKey, { enabled: v })}
          />
        </Space>
      }
    >
      <Row gutter={12}>
        <Col span={12}>
          <Form.Item label="API Key" style={{ marginBottom: 8 }}>
            <Input.Password
              size="small"
              placeholder={meta.placeholder}
              value={config.api_key}
              onChange={(e) => onChange(providerKey, { api_key: e.target.value })}
              style={{ fontFamily: 'monospace' }}
            />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item label="模型" style={{ marginBottom: 8 }}>
            <Select
              size="small"
              value={config.model}
              onChange={(v) => onChange(providerKey, { model: v })}
              options={models}
              style={{ width: '100%' }}
              placeholder="选择模型"
            />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item label="Base URL（可选）" style={{ marginBottom: 8 }}>
            <Input
              size="small"
              placeholder="https://api.openai.com/v1"
              value={config.base_url}
              onChange={(e) => onChange(providerKey, { base_url: e.target.value })}
            />
          </Form.Item>
        </Col>
        <Col span={6}>
          <Form.Item label="Max Tokens" style={{ marginBottom: 8 }}>
            <InputNumber
              size="small"
              min={256}
              max={128000}
              step={512}
              value={config.max_tokens}
              onChange={(v) => onChange(providerKey, { max_tokens: v ?? 4096 })}
              style={{ width: '100%' }}
            />
          </Form.Item>
        </Col>
        <Col span={6}>
          <Form.Item label="Temperature" style={{ marginBottom: 8 }}>
            <InputNumber
              size="small"
              min={0}
              max={2}
              step={0.1}
              value={config.temperature}
              onChange={(v) => onChange(providerKey, { temperature: v ?? 0.7 })}
              style={{ width: '100%' }}
            />
          </Form.Item>
        </Col>
      </Row>
      <Text type="secondary" style={{ fontSize: 12 }}>
        {meta.desc}
      </Text>
      {meta.compatibleList && (
        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 2 }}>
          兼容: {meta.compatibleList}
        </Text>
      )}
    </Card>
  );
};

/* ====== SettingsPage 主组件 ====== */
const SettingsPage: React.FC = () => {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [hasChanges, setHasChanges] = useState(false);
  const [activeTab, setActiveTab] = useState('models');

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
          >
            保存配置
          </Button>
        </Space>
      </div>

      {/* 主标签页 */}
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        type="card"
        style={{ color: '#e0e6f0' }}
        tabBarStyle={{ marginBottom: 16 }}
        items={[
          {
            key: 'models',
            label: (
              <Space>
                <ApiOutlined />
                <span>AI 模型</span>
              </Space>
            ),
            children: (
              <>
                <Text
                  type="secondary"
                  style={{ display: 'block', marginBottom: 16, fontSize: 13 }}
                >
                  配置 AI API 协议。所有兼容 OpenAI 格式的服务商（DeepSeek、Qwen、Kimi 等）使用同一协议配置，Anthropic Claude 使用另一协议配置。
                </Text>
                {Object.keys(PROTOCOL_META).map((pk) => (
                  <ModelProviderCard
                    key={pk}
                    providerKey={pk}
                    config={(settings as any)[pk]}
                    onChange={updateProvider}
                  />
                ))}
              </>
            ),
          },
          {
            key: 'tts',
            label: (
              <Space>
                <AudioOutlined />
                <span>语音合成 (TTS)</span>
              </Space>
            ),
            children: (
              <Card size="small" style={{ borderColor: '#00d4ff44' }}>
                <Row gutter={16}>
                  <Col span={8}>
                    <Form.Item label="启用 TTS">
                      <Switch
                        checked={settings.tts.enabled}
                        onChange={(v) => updateSetting('tts', { enabled: v })}
                      />
                    </Form.Item>
                  </Col>
                  <Col span={8}>
                    <Form.Item label="引擎">
                      <Select
                        value={settings.tts.engine}
                        onChange={(v) => updateSetting('tts', { engine: v })}
                        options={[
                          { label: 'OpenAI TTS', value: 'openai' },
                          { label: 'Edge TTS', value: 'edge' },
                          { label: 'ElevenLabs', value: 'elevenlabs' },
                          { label: 'Fish Speech', value: 'fishspeech' },
                        ]}
                        style={{ width: '100%' }}
                      />
                    </Form.Item>
                  </Col>
                  <Col span={8}>
                    <Form.Item label="发音人">
                      <Input
                        value={settings.tts.voice}
                        onChange={(e) => updateSetting('tts', { voice: e.target.value })}
                        placeholder="nova / alloy / echo ..."
                      />
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item label="语速 (0.25~4.0)">
                      <InputNumber
                        min={0.25}
                        max={4.0}
                        step={0.25}
                        value={settings.tts.speed}
                        onChange={(v) => updateSetting('tts', { speed: v ?? 1.0 })}
                        style={{ width: '100%' }}
                      />
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item label="音调 (0.5~2.0)">
                      <InputNumber
                        min={0.5}
                        max={2.0}
                        step={0.1}
                        value={settings.tts.pitch}
                        onChange={(v) => updateSetting('tts', { pitch: v ?? 1.0 })}
                        style={{ width: '100%' }}
                      />
                    </Form.Item>
                  </Col>
                </Row>
              </Card>
            ),
          },
          {
            key: 'asr',
            label: (
              <Space>
                <AudioOutlined />
                <span>语音识别 (ASR)</span>
              </Space>
            ),
            children: (
              <Card size="small" style={{ borderColor: '#00d4ff44' }}>
                <Row gutter={16}>
                  <Col span={6}>
                    <Form.Item label="启用 ASR">
                      <Switch
                        checked={settings.asr.enabled}
                        onChange={(v) => updateSetting('asr', { enabled: v })}
                      />
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item label="引擎">
                      <Select
                        value={settings.asr.engine}
                        onChange={(v) => updateSetting('asr', { engine: v })}
                        options={[
                          { label: 'Whisper', value: 'whisper' },
                          { label: 'Paraformer', value: 'paraformer' },
                          { label: 'SenseVoice', value: 'sensevoice' },
                          { label: 'Faster Whisper', value: 'faster_whisper' },
                        ]}
                        style={{ width: '100%' }}
                      />
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item label="模型">
                      <Input
                        value={settings.asr.model}
                        onChange={(e) => updateSetting('asr', { model: e.target.value })}
                        placeholder="large-v3 / base ..."
                      />
                    </Form.Item>
                  </Col>
                  <Col span={3}>
                    <Form.Item label="语言">
                      <Select
                        value={settings.asr.language}
                        onChange={(v) => updateSetting('asr', { language: v })}
                        options={[
                          { label: '自动', value: 'auto' },
                          { label: '中文', value: 'zh' },
                          { label: '英文', value: 'en' },
                          { label: '日文', value: 'ja' },
                        ]}
                        style={{ width: '100%' }}
                      />
                    </Form.Item>
                  </Col>
                  <Col span={3}>
                    <Form.Item label="翻译">
                      <Switch
                        checked={settings.asr.translate}
                        onChange={(v) => updateSetting('asr', { translate: v })}
                      />
                    </Form.Item>
                  </Col>
                </Row>
              </Card>
            ),
          },
          {
            key: 'vit',
            label: (
              <Space>
                <EyeOutlined />
                <span>视觉分析 (ViT)</span>
              </Space>
            ),
            children: (
              <Card size="small" style={{ borderColor: '#00d4ff44' }}>
                <Row gutter={16}>
                  <Col span={6}>
                    <Form.Item label="启用视觉分析">
                      <Switch
                        checked={settings.vit.enabled}
                        onChange={(v) => updateSetting('vit', { enabled: v })}
                      />
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item label="协议">
                      <Select
                        value={settings.vit.provider}
                        onChange={(v) => updateSetting('vit', { provider: v })}
                        options={[
                          { label: 'OpenAI 兼容协议', value: 'openai_protocol' },
                          { label: 'Anthropic 协议', value: 'anthropic_protocol' },
                        ]}
                        style={{ width: '100%' }}
                      />
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item
                      label={
                        <Space size={4}>
                          <span>模型</span>
                          <Tooltip title="推荐 Qwen-VL-Max 或 GPT-4o（视觉版）">
                            <InfoCircleOutlined style={{ color: '#6b7b9d' }} />
                          </Tooltip>
                        </Space>
                      }
                    >
                      <Input
                        value={settings.vit.model}
                        onChange={(e) => updateSetting('vit', { model: e.target.value })}
                        placeholder="qwen-vl-max"
                      />
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item label="批处理数">
                      <InputNumber
                        min={1}
                        max={32}
                        value={settings.vit.batch_size}
                        onChange={(v) => updateSetting('vit', { batch_size: v ?? 4 })}
                        style={{ width: '100%' }}
                      />
                    </Form.Item>
                  </Col>
                </Row>
              </Card>
            ),
          },
          {
            key: 'translator',
            label: (
              <Space>
                <TranslationOutlined />
                <span>翻译</span>
              </Space>
            ),
            children: (
              <Card size="small" style={{ borderColor: '#00d4ff44' }}>
                <Row gutter={16}>
                  <Col span={6}>
                    <Form.Item label="启用翻译">
                      <Switch
                        checked={settings.translator.enabled}
                        onChange={(v) => updateSetting('translator', { enabled: v })}
                      />
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item label="协议">
                      <Select
                        value={settings.translator.provider}
                        onChange={(v) => updateSetting('translator', { provider: v })}
                        options={[
                          { label: 'OpenAI 兼容协议', value: 'openai_protocol' },
                          { label: 'Anthropic 协议', value: 'anthropic_protocol' },
                        ]}
                        style={{ width: '100%' }}
                      />
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item label="源语言">
                      <Input
                        value={settings.translator.source_lang}
                        onChange={(e) =>
                          updateSetting('translator', { source_lang: e.target.value })
                        }
                        placeholder="zh / en / ja ..."
                      />
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item label="目标语言">
                      <Input
                        value={settings.translator.target_lang}
                        onChange={(e) =>
                          updateSetting('translator', { target_lang: e.target.value })
                        }
                        placeholder="en / zh ..."
                      />
                    </Form.Item>
                  </Col>
                </Row>
              </Card>
            ),
          },
          {
            key: 'output',
            label: (
              <Space>
                <SettingOutlined />
                <span>输出参数</span>
              </Space>
            ),
            children: (
              <Card size="small" style={{ borderColor: '#00d4ff44' }}>
                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item
                      label={
                        <Space size={4}>
                          <span>输出目录</span>
                          <Tooltip title="最终成片的保存路径">
                            <InfoCircleOutlined style={{ color: '#6b7b9d' }} />
                          </Tooltip>
                        </Space>
                      }
                    >
                      <Input
                        value={settings.output.path}
                        onChange={(e) => updateSetting('output', { path: e.target.value })}
                        placeholder="D:\\Outputs"
                      />
                    </Form.Item>
                  </Col>
                  <Col span={4}>
                    <Form.Item label="画质">
                      <Select
                        value={settings.output.quality}
                        onChange={(v) => updateSetting('output', { quality: v })}
                        options={[
                          { label: '720p', value: '720p' },
                          { label: '1080p', value: '1080p' },
                          { label: '2K', value: '2k' },
                          { label: '4K', value: '4k' },
                        ]}
                        style={{ width: '100%' }}
                      />
                    </Form.Item>
                  </Col>
                  <Col span={4}>
                    <Form.Item label="格式">
                      <Select
                        value={settings.output.format}
                        onChange={(v) => updateSetting('output', { format: v })}
                        options={[
                          { label: 'MP4', value: 'mp4' },
                          { label: 'MOV', value: 'mov' },
                          { label: 'AVI', value: 'avi' },
                        ]}
                        style={{ width: '100%' }}
                      />
                    </Form.Item>
                  </Col>
                  <Col span={4}>
                    <Form.Item label="帧率">
                      <Select
                        value={settings.output.fps}
                        onChange={(v) => updateSetting('output', { fps: v })}
                        options={[
                          { label: '24 fps', value: 24 },
                          { label: '25 fps', value: 25 },
                          { label: '30 fps', value: 30 },
                          { label: '60 fps', value: 60 },
                        ]}
                        style={{ width: '100%' }}
                      />
                    </Form.Item>
                  </Col>
                  <Col span={4}>
                    <Form.Item label="编码">
                      <Select
                        value={settings.output.codec}
                        onChange={(v) => updateSetting('output', { codec: v })}
                        options={[
                          { label: 'H.264', value: 'h264' },
                          { label: 'H.265 / HEVC', value: 'h265' },
                          { label: 'VP9', value: 'vp9' },
                        ]}
                        style={{ width: '100%' }}
                      />
                    </Form.Item>
                  </Col>
                </Row>
              </Card>
            ),
          },
          {
            key: 'hardware',
            label: (
              <Space>
                <ThunderboltOutlined />
                <span>硬件加速</span>
              </Space>
            ),
            children: (
              <Card size="small" style={{ borderColor: '#00d4ff44' }}>
                <Row gutter={16}>
                  <Col span={6}>
                    <Form.Item label="启用硬件加速">
                      <Switch
                        checked={settings.hardware.enabled}
                        onChange={(v) => updateSetting('hardware', { enabled: v })}
                      />
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item label="FFmpeg 加速方式">
                      <Select
                        value={settings.hardware.ffmpeg_hwaccel}
                        onChange={(v) => updateSetting('hardware', { ffmpeg_hwaccel: v })}
                        options={[
                          { label: '自动检测', value: 'auto' },
                          { label: 'NVIDIA CUDA', value: 'cuda' },
                          { label: 'Intel QSV', value: 'qsv' },
                          { label: 'AMD/Intel DXVA2', value: 'dxva2' },
                          { label: 'Apple VideoToolbox', value: 'videotoolbox' },
                          { label: '禁用', value: 'none' },
                        ]}
                        style={{ width: '100%' }}
                      />
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item label="GPU 设备号">
                      <InputNumber
                        min={0}
                        max={7}
                        value={Number(settings.hardware.gpu_device)}
                        onChange={(v) => updateSetting('hardware', { gpu_device: String(v ?? 0) })}
                        style={{ width: '100%' }}
                      />
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item label="编码线程数">
                      <InputNumber
                        min={1}
                        max={64}
                        value={settings.hardware.threads}
                        onChange={(v) => updateSetting('hardware', { threads: v ?? 4 })}
                        style={{ width: '100%' }}
                      />
                    </Form.Item>
                  </Col>
                </Row>
              </Card>
            ),
          },
        ]}
      />
    </div>
  );
};

export default SettingsPage;
