/**
 * ASR 语音识别设置
 */

import React from 'react';
import { Card, Row, Col, Form, Switch, Select, Space } from 'antd';
import { CloudDownloadOutlined } from '@ant-design/icons';
import type { ModelInfo } from './ModelDownloadCard';
import { ModelStatusRow } from './ModelDownloadCard';

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
}

export const ASRTab: React.FC<ASRTabProps> = ({
  asrConfig,
  onASRChange,
  models,
  modelDownloads,
  onDownload,
  onDelete,
}) => {
  const whisperModels = [
    { label: 'Tiny (轻量快速)', value: 'tiny' },
    { label: 'Base (基础款)', value: 'base' },
    { label: 'Small (中等)', value: 'small' },
    { label: 'Medium (大模型)', value: 'medium' },
    { label: 'Large V3 (旗舰效果)', value: 'large-v3' },
  ];
  const sensevoiceModels = [
    { label: 'SenseVoice Large (本地极速且最佳)', value: 'SenseVoice-large' },
  ];

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
                options={asrConfig.engine === 'sensevoice' ? sensevoiceModels : whisperModels}
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
        style={{ borderColor: '#722ed144' }}
      >
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          {models.filter((m) => m.category === 'asr').map((model) => (
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
    </>
  );
};
