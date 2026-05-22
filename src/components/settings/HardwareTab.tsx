import React from 'react';
import { Card, Row, Col, Form, Switch, Select, InputNumber } from 'antd';
import { InfoCircleOutlined } from '@ant-design/icons';

import type { HardwareConfig } from '../../services/ipc';

interface HardwareTabProps {
  hardwareConfig: HardwareConfig;
  onHardwareChange: (value: Partial<HardwareConfig>) => void;
}

export const HardwareTab: React.FC<HardwareTabProps> = ({ hardwareConfig, onHardwareChange }) => (
  <Card size="small" style={{ borderColor: '#00d4ff44' }}>
    <Row gutter={[16, 16]}>
      <Col span={6}>
        <Form.Item label="启用硬件加速">
          <Switch
            checked={hardwareConfig.enabled}
            onChange={(v) => onHardwareChange({ enabled: v })}
          />
        </Form.Item>
      </Col>
      <Col span={6}>
        <Form.Item label="FFmpeg 加速方式">
          <Select
            value={hardwareConfig.ffmpeg_hwaccel}
            onChange={(v) => onHardwareChange({ ffmpeg_hwaccel: v })}
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
            min={0} max={7}
            value={Number(hardwareConfig.gpu_device)}
            onChange={(v) => onHardwareChange({ gpu_device: String(v ?? 0) })}
            style={{ width: '100%' }}
          />
        </Form.Item>
      </Col>
      <Col span={6}>
        <Form.Item label="编码线程数">
          <InputNumber
            min={1} max={64}
            value={hardwareConfig.threads}
            onChange={(v) => onHardwareChange({ threads: v ?? 4 })}
            style={{ width: '100%' }}
          />
        </Form.Item>
      </Col>
      <Col span={6}>
        <Form.Item label="并发任务数">
          <InputNumber
            min={1} max={16}
            value={hardwareConfig.max_workers}
            onChange={(v) => onHardwareChange({ max_workers: v ?? 5 })}
            style={{ width: '100%' }}
          />
        </Form.Item>
      </Col>

      <Col span={24} style={{ marginTop: 8 }}>
        {hardwareConfig.max_workers >= 3 ? (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            fontSize: 12,
            color: '#faad14',
            backgroundColor: '#faad1411',
            padding: '10px 16px',
            borderRadius: 6,
            border: '1px solid #faad1433',
            lineHeight: '1.6'
          }}>
            <InfoCircleOutlined style={{ fontSize: 14, flexShrink: 0 }} />
            <span>
              <strong>⚠️ 高并发负载提醒：</strong>当前并发任务数设置为 {hardwareConfig.max_workers}。在多视频同时进行 AI 分析（ASR 语音识别、ViT 视觉多模态分析）时，多个模型会同时载入显存或内存，这会急剧增加硬件压力。<strong>建议显存 &lt; 8G 的机型设为 1-2，显存 &gt;= 12G 的机型设为 3-4。</strong>设置为 5 以上有极高几率在本地运行 AI 模型时引发 OOM 错误导致程序闪退。
            </span>
          </div>
        ) : (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            fontSize: 12,
            color: '#52c41a',
            backgroundColor: '#52c41a11',
            padding: '10px 16px',
            borderRadius: 6,
            border: '1px solid #52c41a33',
            lineHeight: '1.6'
          }}>
            <InfoCircleOutlined style={{ fontSize: 14, flexShrink: 0 }} />
            <span>
              <strong>🟢 安全并发级别：</strong>当前并发任务数设置为 {hardwareConfig.max_workers}。系统能够极其平稳地轮询和调度多视频任务，显存和系统内存负载安全，适合绝大部分标准硬件配置。
            </span>
          </div>
        )}
      </Col>
    </Row>
  </Card>
);
