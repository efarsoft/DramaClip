/**
 * ASR 语音识别设置 Tab
 */

import React, { useState } from 'react';
import { Card, Row, Col, Form, Switch, Select, Space, Button, Modal, Input, Radio, message } from 'antd';
import { CloudDownloadOutlined, PlusOutlined } from '@ant-design/icons';
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

interface ASRTabProps {
  asrConfig: {
    enabled: boolean;
    engine: string;
    model: string;
    language: string;
    translate: boolean;
    enable_emotion?: boolean;
    enable_audio_events?: boolean;
  };
  onASRChange: (value: Partial<{
    enabled: boolean;
    engine: string;
    model: string;
    language: string;
    translate: boolean;
    enable_emotion?: boolean;
    enable_audio_events?: boolean;
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

export const ASRTab: React.FC<ASRTabProps> = ({
  asrConfig,
  onASRChange,
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

  // Dynamically populate model options
  const whisperModels = models
    .filter((m) => m.category === 'asr' && m.type === 'whisper')
    .map((m) => ({
      label: `${m.name} (${m.downloaded ? '已部署' : '未部署'})`,
      value: m.id.replace('whisper-', ''),
    }));

  const sensevoiceModels = models
    .filter((m) => m.category === 'asr' && m.type === 'sensevoice')
    .map((m) => ({
      label: `${m.name} (${m.downloaded ? '已部署' : '未部署'})`,
      value: m.id,
    }));

  const customASROptions = models
    .filter((m) => m.category === 'asr' && m.type === 'custom')
    .map((m) => ({
      label: `[自定义] ${m.name} (${m.downloaded ? '已加载' : '无效路径'})`,
      value: m.id,
    }));

  const whisperOptions = [...whisperModels, ...customASROptions];
  const sensevoiceOptions = [...sensevoiceModels, ...customASROptions];

  // Handle adding custom model
  const handleAddCustomModel = async () => {
    try {
      const values = await form.validateFields();
      const id = `custom-asr-${Date.now()}`;
      
      const newModel: CustomModelConfig = {
        id,
        name: values.name,
        mode: values.mode,
        path: values.mode === 'Local Path' ? values.path : '',
        onlineId: values.mode === 'Online ID' ? values.onlineId : '',
        description: values.description || '用户导入的自定义 ASR 识别模型',
      };

      const currentList = customModels?.asr || [];
      onCustomModelsChange({
        asr: [...currentList, newModel],
      });

      setModalVisible(false);
      form.resetFields();
      setMode('Local Path');
      message.success(`自定义模型 ${values.name} 注册成功`);
    } catch (err) {
      // Form validation error
    }
  };

  return (
    <>
      <Card size="small" style={{ borderColor: '#00d4ff44', marginBottom: 12 }}>
        <Row gutter={[16, 12]}>
          <Col span={4}>
            <Form.Item label="启用 ASR">
              <Switch checked={asrConfig.enabled} onChange={(v) => onASRChange({ enabled: v })} />
            </Form.Item>
          </Col>
          <Col span={5}>
            <Form.Item label="引擎">
              <Select
                value={asrConfig.engine}
                onChange={(v) => onASRChange({ engine: v })}
                options={[
                  { label: 'Faster Whisper (离线高精)', value: 'faster_whisper' },
                  { label: 'SenseVoice (本地极速-推荐)', value: 'sensevoice' },
                ]}
                style={{ width: '100%' }}
              />
            </Form.Item>
          </Col>
          <Col span={5}>
            <Form.Item label="模型">
              <Select
                value={asrConfig.model}
                onChange={(v) => onASRChange({ model: v })}
                options={asrConfig.engine === 'sensevoice' ? sensevoiceOptions : whisperOptions}
                style={{ width: '100%' }}
              />
            </Form.Item>
          </Col>
          <Col span={5}>
            <Form.Item label="语言">
              <Select
                value={asrConfig.language}
                onChange={(v) => onASRChange({ language: v })}
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
          <Col span={5}>
            <Form.Item label="翻译为英文">
              <Switch
                checked={asrConfig.translate}
                onChange={(v) => onASRChange({ translate: v })}
                disabled={asrConfig.engine === 'sensevoice'}
              />
            </Form.Item>
          </Col>
        </Row>
        {asrConfig.engine === 'sensevoice' && (
          <Row gutter={16} style={{ marginTop: 12, borderTop: '1px solid #ffffff11', paddingTop: 12 }}>
            <Col span={6}>
              <Form.Item label="富文本情感检测 (情感/语速标签)">
                <Switch
                  checked={asrConfig.enable_emotion ?? true}
                  onChange={(v) => onASRChange({ enable_emotion: v })}
                />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item label="声音事件检测 (BGM/掌声/笑声等)">
                <Switch
                  checked={asrConfig.enable_audio_events ?? true}
                  onChange={(v) => onASRChange({ enable_audio_events: v })}
                />
              </Form.Item>
            </Col>
          </Row>
        )}
      </Card>

      {/* ASR 模型管理 */}
      <Card
        size="small"
        title={
          <Space>
            <CloudDownloadOutlined />
            <span>ASR 语音识别模型管理</span>
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
          {models
            .filter((m) => m.category === 'asr')
            .map((model) => (
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

      {/* Add Custom Model Modal */}
      <Modal
        title="导入自定义 ASR 模型配置"
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
            <Input placeholder="例如: My-Custom-Whisper-Base" />
          </Form.Item>

          <Form.Item name="mode" label="导入模式">
            <Radio.Group>
              <Radio.Button value="Local Path">本地目录导入</Radio.Button>
              <Radio.Button value="Online ID">线上 Repo 注册</Radio.Button>
            </Radio.Group>
          </Form.Item>

          {mode === 'Local Path' ? (
            <Form.Item
              name="path"
              label="本地模型绝对路径"
              rules={[{ required: true, message: '请输入物理绝对路径' }]}
              extra="请输入存放 model.bin/model.onnx 等结构文件的本地绝对物理目录"
            >
              <Input placeholder="D:\models\my-whisper-small" />
            </Form.Item>
          ) : (
            <Form.Item
              name="onlineId"
              label="线上 HuggingFace/ModelScope Repo ID"
              rules={[{ required: true, message: '请输入线上模型 ID' }]}
              extra="例如: Systran/faster-whisper-small"
            >
              <Input placeholder="Systran/faster-whisper-small" />
            </Form.Item>
          )}

          <Form.Item name="description" label="模型功能定位与适用场景描述">
            <Input.TextArea placeholder="例如: 针对垂直领域专业术语微调后的 ASR 模型，适合科研/医疗剧本转写。" rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
};
