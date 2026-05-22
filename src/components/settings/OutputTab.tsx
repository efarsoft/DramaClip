/**
 * 输出参数设置
 */

import React from 'react';
import { Card, Row, Col, Form, Select, Input, Space, Tooltip } from 'antd';
import { InfoCircleOutlined, FolderOpenOutlined } from '@ant-design/icons';

import type { OutputConfig } from '../../services/ipc';

interface OutputTabProps {
  outputConfig: OutputConfig;
  onOutputChange: (value: Partial<OutputConfig>) => void;
}

export const OutputTab: React.FC<OutputTabProps> = ({ outputConfig, onOutputChange }) => {
  const handleSelectFolder = async () => {
    if (window.electronAPI?.dialog?.openFolder) {
      try {
        const result = await window.electronAPI.dialog.openFolder();
        if (result?.success && result?.data) {
          onOutputChange({ path: result.data });
        }
      } catch (err) {
        console.error('选择目录失败:', err);
      }
    }
  };

  return (
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
              value={outputConfig.path}
              onChange={(e) => onOutputChange({ path: e.target.value })}
              placeholder="D:\\Outputs"
              suffix={
                window.electronAPI ? (
                  <FolderOpenOutlined
                    style={{ color: '#00d4ff', cursor: 'pointer', fontSize: 16 }}
                    onClick={handleSelectFolder}
                  />
                ) : null
              }
            />
          </Form.Item>
        </Col>
        <Col span={4}>
          <Form.Item label="画质">
            <Select
              value={outputConfig.quality}
              onChange={(v) => onOutputChange({ quality: v })}
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
              value="mp4"
              disabled
              options={[
                { label: 'MP4', value: 'mp4' },
              ]}
              style={{ width: '100%' }}
            />
          </Form.Item>
        </Col>
        <Col span={4}>
          <Form.Item label="帧率">
            <Select
              value={outputConfig.fps}
              onChange={(v) => onOutputChange({ fps: v })}
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
              value={outputConfig.codec}
              onChange={(v) => onOutputChange({ codec: v })}
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
  );
};
