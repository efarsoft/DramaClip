import React, { useState } from 'react';
import { Card, Form, Input, Select, InputNumber, Space, Row, Col, Switch, Button, Segmented, message } from 'antd';
import { ApiOutlined, InfoCircleOutlined, KeyOutlined, LinkOutlined, CloudDownloadOutlined } from '@ant-design/icons';

import type { ModelProviderConfig } from '../../services/ipc';

interface AIModelsTabProps {
  openaiConfig: ModelProviderConfig;
  anthropicConfig: ModelProviderConfig;
  onChange: (key: string, value: Partial<ModelProviderConfig>) => void;
}

const PROTOCOL_META: Record<string, {
  name: string;
  desc: string;
  placeholder: string;
  compatibleList: string;
  modelOptions: { label: string; value: string }[];
}> = {
  openai_protocol: {
    name: 'OpenAI 兼容协议',
    desc: '兼容所有 OpenAI API 格式的服务商',
    placeholder: '请输入 API Key (例如 sk-...)',
    compatibleList: 'OpenAI, DeepSeek, 通义千问, Kimi, Groq, Together AI, Ollama',
    modelOptions: [
      { label: 'GPT-4o (推荐旗舰)', value: 'gpt-4o' },
      { label: 'GPT-4o-mini (推荐高性价比)', value: 'gpt-4o-mini' },
      { label: 'DeepSeek Chat (极力推荐)', value: 'deepseek-chat' },
      { label: 'DeepSeek Reasoner (推理模型)', value: 'deepseek-reasoner' },
      { label: 'Qwen Max (通义千问旗舰)', value: 'qwen-max' },
      { label: 'Qwen Plus (通义千问性价比)', value: 'qwen-plus' },
      { label: 'Kimi (Moonshot v1 Auto)', value: 'moonshot-v1-auto' },
    ],
  },
  anthropic_protocol: {
    name: 'Anthropic 兼容协议',
    desc: '兼容 Anthropic Claude API 格式',
    placeholder: '请输入 Claude API Key (例如 sk-ant-...)',
    compatibleList: 'Anthropic Claude 3.5 / 3',
    modelOptions: [
      { label: 'Claude 3.5 Sonnet (最强代码与逻辑)', value: 'claude-3-5-sonnet-latest' },
      { label: 'Claude 3.5 Haiku (极速版)', value: 'claude-3-5-haiku-latest' },
      { label: 'Claude 3 Opus (经典旗舰)', value: 'claude-3-opus-latest' },
    ],
  },
};

export const AIModelsTab: React.FC<AIModelsTabProps> = ({
  openaiConfig,
  anthropicConfig,
  onChange,
}) => {
  const [activeChannel, setActiveChannel] = useState<'openai_protocol' | 'anthropic_protocol'>('openai_protocol');
  const [searchText, setSearchText] = useState('');
  const [fetching, setFetching] = useState(false);
  const [fetchedModels, setFetchedModels] = useState<string[]>([]);

  const config = activeChannel === 'openai_protocol' ? openaiConfig : anthropicConfig;
  const meta = PROTOCOL_META[activeChannel];

  // 动态获取/拉取模型列表
  const handleFetchModels = async () => {
    if (!config.api_key) {
      message.warning('请先输入 API Key 才能拉取模型列表！');
      return;
    }
    
    setFetching(true);
    try {
      let baseUrl = config.base_url || (activeChannel === 'openai_protocol' ? 'https://api.openai.com/v1' : 'https://api.anthropic.com');
      baseUrl = baseUrl.trim().replace(/\/+$/, ''); // 去除末尾斜杠
      
      const modelsUrl = `${baseUrl}/models`;
      const headers: Record<string, string> = {
        'Authorization': `Bearer ${config.api_key}`,
        'Content-Type': 'application/json'
      };
      
      if (activeChannel === 'anthropic_protocol') {
        headers['x-api-key'] = config.api_key;
        headers['anthropic-version'] = '2023-06-01';
      }
      
      const res = await fetch(modelsUrl, { headers });
      if (!res.ok) {
        throw new Error(`HTTP 请求失败: ${res.status}`);
      }
      
      const data = await res.json();
      if (data && Array.isArray(data.data)) {
        const list = data.data.map((m: any) => m.id);
        if (list.length > 0) {
          setFetchedModels(list);
          message.success(`成功从服务商拉取并导入 ${list.length} 个可用模型！`);
        } else {
          message.warning('未在服务商响应中发现任何可用模型列表');
        }
      } else {
        throw new Error('未识别的模型列表返回格式');
      }
    } catch (err: any) {
      console.error(err);
      message.error(`拉取失败: ${err.message || '网络连接或跨域受阻'}`);
    } finally {
      setFetching(false);
    }
  };

  // 合并预设、拉取的模型与自定义输入
  const dynamicModelOptions = [...meta.modelOptions];
  
  fetchedModels.forEach(m => {
    if (!dynamicModelOptions.some(opt => opt.value === m)) {
      dynamicModelOptions.push({ label: m, value: m });
    }
  });

  if (searchText && !dynamicModelOptions.some(opt => opt.value === searchText)) {
    dynamicModelOptions.unshift({
      label: `自定义模型: "${searchText}"`,
      value: searchText,
    });
  }

  return (
    <Card
      size="small"
      title={
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
          <Space>
            <ApiOutlined style={{ color: config.enabled ? '#00d4ff' : '#8c95a8' }} />
            <span style={{ color: config.enabled ? '#e0e6f0' : '#8c95a8' }}>AI 通道与大模型配置</span>
          </Space>
        </div>
      }
      extra={
        <Space size={12}>
          <span style={{ fontSize: 12, color: config.enabled ? '#00d4ff' : '#8c95a8' }}>
            {config.enabled ? '当前通道已启用' : '当前通道已禁用'}
          </span>
          <Switch
            size="small"
            checked={config.enabled}
            onChange={(checked) => onChange(activeChannel, { enabled: checked })}
          />
        </Space>
      }
      style={{
        borderColor: config.enabled ? '#00d4ff44' : '#ffffff11',
        backgroundColor: config.enabled ? '#141b2b' : 'transparent',
        transition: 'all 0.3s ease',
        marginBottom: 16
      }}
    >
      <div style={{ marginBottom: 16, borderBottom: '1px solid #ffffff11', paddingBottom: 16 }}>
        <span style={{ marginRight: 12, fontSize: 13, color: '#e0e6f0' }}>选择配置协议通道:</span>
        <Segmented
          options={[
            { label: 'OpenAI 兼容协议', value: 'openai_protocol' },
            { label: 'Anthropic 协议', value: 'anthropic_protocol' }
          ]}
          value={activeChannel}
          onChange={(v) => {
            setActiveChannel(v as any);
            setFetchedModels([]);
            setSearchText('');
          }}
        />
      </div>

      <Row gutter={[16, 16]}>
        <Col span={12}>
          <Form.Item
            label={
              <Space size={4}>
                <KeyOutlined style={{ color: '#00d4ff' }} />
                <span>API Key</span>
              </Space>
            }
            required
          >
            <Input.Password
              value={config.api_key}
              onChange={(e) => onChange(activeChannel, { api_key: e.target.value })}
              placeholder={meta.placeholder}
              maxLength={200}
              disabled={!config.enabled}
            />
          </Form.Item>
        </Col>
        
        <Col span={12}>
          <Form.Item
            label={
              <Space size={4}>
                <LinkOutlined style={{ color: '#00d4ff' }} />
                <span>API Base URL (代理地址)</span>
              </Space>
            }
          >
            <Input
              value={config.base_url}
              onChange={(e) => onChange(activeChannel, { base_url: e.target.value })}
              placeholder={activeChannel === 'openai_protocol' ? 'https://api.openai.com/v1' : 'https://api.anthropic.com'}
              disabled={!config.enabled}
            />
          </Form.Item>
        </Col>

        <Col span={12}>
          <Form.Item label="大语言模型 (Model)" style={{ marginBottom: 0 }}>
            <div style={{ display: 'flex', gap: 8 }}>
              <Select
                value={config.model}
                onChange={(v) => onChange(activeChannel, { model: v })}
                options={dynamicModelOptions}
                showSearch
                disabled={!config.enabled}
                placeholder="请选择预设音色/通道模型或输入"
                onSearch={(val) => setSearchText(val)}
                filterOption={(input, option) =>
                  (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
                }
                style={{ flex: 1 }}
              />
              <Button
                type="dashed"
                icon={<CloudDownloadOutlined />}
                onClick={handleFetchModels}
                loading={fetching}
                disabled={!config.enabled}
              >
                拉取模型
              </Button>
            </div>
          </Form.Item>
        </Col>

        <Col span={6}>
          <Form.Item label="最大 Token (Max Tokens)" style={{ marginBottom: 0 }}>
            <InputNumber
              min={256} max={128000} step={512}
              value={config.max_tokens}
              onChange={(v) => onChange(activeChannel, { max_tokens: v ?? 4096 })}
              disabled={!config.enabled}
              style={{ width: '100%' }}
            />
          </Form.Item>
        </Col>

        <Col span={6}>
          <Form.Item label="温度参数 (Temperature)" style={{ marginBottom: 0 }}>
            <InputNumber
              min={0.0} max={2.0} step={0.1}
              value={config.temperature}
              onChange={(v) => onChange(activeChannel, { temperature: v ?? 0.7 })}
              disabled={!config.enabled}
              style={{ width: '100%' }}
            />
          </Form.Item>
        </Col>

        <Col span={24} style={{ marginTop: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#8c95a8' }}>
            <InfoCircleOutlined style={{ color: '#00d4ff' }} />
            <span>
              <strong>服务支持：</strong>{meta.desc} — 已测试兼容 {meta.compatibleList} 等服务商。
            </span>
          </div>
        </Col>
      </Row>
    </Card>
  );
};
