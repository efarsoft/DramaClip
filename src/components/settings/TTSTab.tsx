/**
 * TTS 语音合成设置 Tab
 */

import React, { useState } from 'react';
import { Card, Form, Row, Col, Switch, Select, InputNumber, Space, Button, Modal, Input, Radio, message } from 'antd';
import { AudioOutlined, PlusOutlined } from '@ant-design/icons';
import type { ModelInfo } from './ModelDownloadCard';
import { ModelStatusRow } from './ModelDownloadCard';

interface CustomModelConfig {
  id: string;
  name: string;
  mode: 'Local Path' | 'Online ID';
  path?: string;
  onlineId?: string;
  description?: string;
}

interface TTSTabProps {
  ttsConfig: {
    enabled: boolean;
    engine: string;
    voice: string;
    speed: number;
    pitch: number;
  };
  onTTSChange: (value: Partial<{
    enabled: boolean;
    engine: string;
    voice: string;
    speed: number;
    pitch: number;
  }>) => void;
  models: ModelInfo[];
  modelDownloads: Record<string, { progress: number; message: string }>;
  onDownload: (modelId: string) => void;
  onDelete: (modelId: string, modelName: string) => void;
  customModels?: {
    asr: CustomModelConfig[];
    tts: CustomModelConfig[];
  };
  onCustomModelsChange: (v: { asr?: CustomModelConfig[]; tts?: CustomModelConfig[] }) => void;
}

const engineOptions = [
  { label: 'Supertonic TTS (本地超快 - 推荐)', value: 'supertonic' },
  { label: 'StyleTTS 2 (本地艺术级)', value: 'styletts2' },
  { label: 'Edge TTS (免费云端免Key)', value: 'edge' },
  { label: 'OpenAI TTS (官方 API)', value: 'openai' },
  { label: 'CosyVoice / SoulVoice (克隆级)', value: 'soulvoice' },
];

export const TTSTab: React.FC<TTSTabProps> = ({
  ttsConfig,
  onTTSChange,
  models,
  modelDownloads,
  onDownload,
  onDelete,
  customModels,
  onCustomModelsChange,
}) => {
  const [modalVisible, setModalVisible] = useState(false);
  const [form] = Form.useForm();
  const [mode, setMode] = useState<'Local Path' | 'Online ID'>('Local Path');

  const getVoiceOptions = () => {
    switch (ttsConfig.engine) {
      case 'supertonic':
        return [
          { label: 'M1 (稳重男声)', value: 'M1' },
          { label: 'M2 (磁性男声)', value: 'M2' },
          { label: 'F1 (温柔女声)', value: 'F1' },
          { label: 'F2 (甜美女声)', value: 'F2' },
        ];
      case 'styletts2':
        return [{ label: 'Default (标准单说话人)', value: 'default' }];
      case 'edge':
        return [
          { label: '晓晓 (女-柔美)', value: 'zh-CN-XiaoxiaoNeural' },
          { label: '云希 (男-解说必选)', value: 'zh-CN-YunxiNeural' },
          { label: '云健 (男-影视解说)', value: 'zh-CN-YunjianNeural' },
          { label: '辽宁晓北 (东北女腔)', value: 'zh-CN-liaoning-XiaobeiNeural' },
          { label: '四川寰宇 (西南男腔)', value: 'zh-CN-Sichuan-YunxiNeural' },
          { label: 'Aria (英文女声)', value: 'en-US-AriaNeural' },
          { label: 'Guy (英文男声)', value: 'en-US-GuyNeural' },
        ];
      case 'openai':
        return [
          { label: 'Alloy (自然中性)', value: 'alloy' },
          { label: 'Echo (温暖男声)', value: 'echo' },
          { label: 'Fable (醇厚男声)', value: 'fable' },
          { label: 'Onyx (深沉男声)', value: 'onyx' },
          { label: 'Nova (清亮女声)', value: 'nova' },
          { label: 'Shimmer (知性女声)', value: 'shimmer' },
        ];
      case 'soulvoice':
        return [
          { label: 'Default (精品中文女声)', value: 'default' },
          { label: 'CosyVoice Reference (自定义克隆)', value: 'reference' },
        ];
      default:
        return [{ label: 'Default', value: 'default' }];
    }
  };

  const ttsModels = models.filter((m) => m.category === 'tts');

  // Dynamically append custom TTS options to the synthesis engines
  const customTTSOptions = models
    .filter((m) => m.category === 'tts' && m.type === 'custom')
    .map((m) => ({
      label: `[自定义] ${m.name} (${m.downloaded ? '已加载' : '无效路径'})`,
      value: m.id,
    }));

  const allEngineOptions = [...engineOptions, ...customTTSOptions];

  // Handle adding custom TTS model
  const handleAddCustomModel = async () => {
    try {
      const values = await form.validateFields();
      const id = `custom-tts-${Date.now()}`;

      const newModel: CustomModelConfig = {
        id,
        name: values.name,
        mode: values.mode,
        path: values.mode === 'Local Path' ? values.path : '',
        onlineId: values.mode === 'Online ID' ? values.onlineId : '',
        description: values.description || '用户导入的自定义 TTS 语音合成模型',
      };

      const currentList = customModels?.tts || [];
      onCustomModelsChange({
        tts: [...currentList, newModel],
      });

      setModalVisible(false);
      form.resetFields();
      setMode('Local Path');
      message.success(`自定义模型 ${values.name} 注册成功`);
    } catch (err) {
      // Validation error
    }
  };

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={12}>
      {/* --- TTS 配置 --- */}
      <Card
        size="small"
        title={
          <Space>
            <AudioOutlined style={{ color: '#00d4ff' }} />
            <span>TTS 语音合成配置</span>
          </Space>
        }
        style={{ borderColor: '#00d4ff44' }}
      >
        <Row gutter={[24, 16]}>
          <Col span={8}>
            <Form.Item label="启用 TTS">
              <Switch checked={ttsConfig.enabled} onChange={(v) => onTTSChange({ enabled: v })} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item label="合成引擎">
              <Select
                value={ttsConfig.engine}
                onChange={(v) => {
                  let defaultVoice = 'default';
                  if (v === 'supertonic') defaultVoice = 'M1';
                  else if (v === 'edge') defaultVoice = 'zh-CN-YunxiNeural';
                  else if (v === 'openai') defaultVoice = 'alloy';
                  onTTSChange({ engine: v, voice: defaultVoice });
                }}
                options={allEngineOptions}
                style={{ width: '100%' }}
              />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item label="音色">
              <Select
                value={ttsConfig.voice}
                onChange={(v) => onTTSChange({ voice: v })}
                options={getVoiceOptions()}
                style={{ width: '100%' }}
              />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label="语速调节">
              <InputNumber
                min={0.5} max={3.0} step={0.1}
                value={ttsConfig.speed}
                onChange={(v) => onTTSChange({ speed: v ?? 1.0 })}
                style={{ width: '100%' }}
              />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label="音高调节 (Pitch)">
              <InputNumber
                min={0.5} max={2.0} step={0.1}
                value={ttsConfig.pitch}
                onChange={(v) => onTTSChange({ pitch: v ?? 1.0 })}
                style={{ width: '100%' }}
              />
            </Form.Item>
          </Col>
        </Row>
      </Card>

      {/* --- TTS 模型管理 --- */}
      {ttsModels.length > 0 && (
        <Card
          size="small"
          title={
            <Space>
              <span>TTS 语音合成模型管理</span>
            </Space>
          }
          extra={
            <Button
              type="primary"
              ghost
              size="small"
              icon={<PlusOutlined />}
              onClick={() => setModalVisible(true)}
              style={{ borderRadius: '4px' }}
            >
              导入自定义模型
            </Button>
          }
          style={{ borderColor: '#722ed144' }}
        >
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            {ttsModels.map((model) => (
              <ModelStatusRow
                key={model.id}
                model={model}
                downloadInfo={modelDownloads[model.id]}
                onDownload={onDownload}
                onDelete={onDelete}
              />
            ))}
          </Space>
        </Card>
      )}

      {/* Add Custom Model Modal */}
      <Modal
        title="导入自定义 TTS 模型配置"
        open={modalVisible}
        onOk={handleAddCustomModel}
        onCancel={() => {
          setModalVisible(false);
          form.resetFields();
          setMode('Local Path');
        }}
        okText="确认导入"
        cancelText="取消"
        width={520}
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ mode: 'Local Path' }}
          onValuesChange={(changed) => {
            if (changed.mode) setMode(changed.mode);
          }}
          style={{ marginTop: 16 }}
        >
          <Form.Item
            name="name"
            label="模型显示名称"
            rules={[{ required: true, message: '请输入显示名称' }]}
          >
            <Input placeholder="例如: My-Custom-TTS-Model" />
          </Form.Item>

          <Form.Item name="mode" label="导入模式">
            <Radio.Group>
              <Radio.Group>
                <Radio.Button value="Local Path">本地目录导入</Radio.Button>
                <Radio.Button value="Online ID">线上 Repo 注册</Radio.Button>
              </Radio.Group>
            </Radio.Group>
          </Form.Item>

          {mode === 'Local Path' ? (
            <Form.Item
              name="path"
              label="本地模型绝对路径"
              rules={[{ required: true, message: '请输入物理绝对路径' }]}
              extra="请输入存放 model.onnx/config.json 等结构文件的本地绝对物理目录"
            >
              <Input placeholder="D:\models\my-tts-model" />
            </Form.Item>
          ) : (
            <Form.Item
              name="onlineId"
              label="线上 HuggingFace/ModelScope Repo ID"
              rules={[{ required: true, message: '请输入线上模型 ID' }]}
              extra="例如: supertone-inc/supertonic"
            >
              <Input placeholder="supertone-inc/supertonic" />
            </Form.Item>
          )}

          <Form.Item name="description" label="模型功能定位与适用场景描述">
            <Input.TextArea placeholder="例如: 针对甜美播音腔微调后的 TTS 模型，适合有声书/剧本旁白配音。" rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  );
};
