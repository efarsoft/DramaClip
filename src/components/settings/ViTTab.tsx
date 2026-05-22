import React, { useState } from 'react';
import { Card, Row, Col, Form, Switch, Select, InputNumber, Space, Tooltip } from 'antd';
import { InfoCircleOutlined } from '@ant-design/icons';

import type { VitConfig } from '../../services/ipc';

interface ViTTabProps {
  vitConfig: VitConfig;
  onViTChange: (value: Partial<VitConfig>) => void;
}

const RECOMMENDED_VIT_MODELS = [
  { label: 'Qwen VL Max (极力推荐 — 视觉效果最佳)', value: 'qwen-vl-max' },
  { label: 'Qwen VL Plus (高性价比 — 快速视觉解析)', value: 'qwen-vl-plus' },
  { label: 'GPT-4o (旗舰视觉 — 顶尖的多模态理解)', value: 'gpt-4o' },
  { label: 'Claude 3.5 Sonnet (最强逻辑视觉模型)', value: 'claude-3-5-sonnet-latest' },
];

export const ViTTab: React.FC<ViTTabProps> = ({ vitConfig, onViTChange }) => {
  const [searchText, setSearchText] = useState('');

  // 合并预设推荐模型与用户自定义搜索模型
  const dynamicModelOptions = [...RECOMMENDED_VIT_MODELS];
  
  if (searchText && !dynamicModelOptions.some(opt => opt.value === searchText)) {
    dynamicModelOptions.unshift({
      label: `自定义模型: "${searchText}"`,
      value: searchText,
    });
  }

  // 确保当前值在 options 中存在，免得渲染纯字符串
  if (vitConfig.model && !dynamicModelOptions.some(opt => opt.value === vitConfig.model)) {
    dynamicModelOptions.push({
      label: `当前配置: "${vitConfig.model}"`,
      value: vitConfig.model,
    });
  }

  return (
    <Card size="small" style={{ borderColor: '#00d4ff44' }}>
      <Row gutter={16}>
        <Col span={6}>
          <Form.Item label="启用视觉分析">
            <Switch
              checked={vitConfig.enabled}
              onChange={(v) => onViTChange({ enabled: v })}
            />
          </Form.Item>
        </Col>
        <Col span={6}>
          <Form.Item label="协议">
            <Select
              value={vitConfig.provider}
              onChange={(v) => onViTChange({ provider: v })}
              options={[
                { label: 'OpenAI 兼容协议', value: 'openai_protocol' },
                { label: 'Anthropic 协议', value: 'anthropic_protocol' },
              ]}
              style={{ width: '100%' }}
            />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item
            label={
              <Space size={4}>
                <span>视觉模型 (Model)</span>
                <Tooltip title="推荐使用 Qwen-VL-Max 或 GPT-4o（需在第一页AI模型中配置并启用对应的 OpenAI/Anthropic 协议通道）">
                  <InfoCircleOutlined style={{ color: '#6b7b9d' }} />
                </Tooltip>
              </Space>
            }
          >
            <Select
              value={vitConfig.model}
              onChange={(v) => onViTChange({ model: v })}
              options={dynamicModelOptions}
              showSearch
              placeholder="请选择或直接输入大模型名称"
              onSearch={(val) => setSearchText(val)}
              filterOption={(input, option) =>
                (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
              }
              style={{ width: '100%' }}
            />
          </Form.Item>
        </Col>
        <Col span={4}>
          <Form.Item label="批处理数">
            <InputNumber
              min={1} max={32}
              value={vitConfig.batch_size}
              onChange={(v) => onViTChange({ batch_size: v ?? 4 })}
              style={{ width: '100%' }}
            />
          </Form.Item>
        </Col>
      </Row>
    </Card>
  );
};
