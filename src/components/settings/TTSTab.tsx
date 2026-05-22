/**
 * TTS 语音合成设置
 */

import React from 'react';
import { Card, Form, Row, Col, Switch, Select, InputNumber, Space } from 'antd';
import { AudioOutlined } from '@ant-design/icons';
import type { ModelInfo } from './ModelDownloadCard';
import { ModelStatusRow } from './ModelDownloadCard';

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
}) => {
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
                  // 自动切换为该引擎的第一个默认声音
                  let defaultVoice = 'default';
                  if (v === 'supertonic') defaultVoice = 'M1';
                  else if (v === 'edge') defaultVoice = 'zh-CN-YunxiNeural';
                  else if (v === 'openai') defaultVoice = 'alloy';
                  onTTSChange({ engine: v, voice: defaultVoice });
                }}
                options={engineOptions}
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
          style={{ borderColor: '#722ed144' }}
        >
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
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
    </Space>
  );
};
