/**
 * 导出发布面板 — 项目工作区 Step 5
 */

import React, { useState, useRef, useEffect } from 'react';
import { Typography, Button, Card, Space, Progress, Select, message, Tag } from 'antd';
import {
  ExportOutlined,
  CheckCircleFilled,
  FolderOpenOutlined,
} from '@ant-design/icons';
import { useProjectStore } from '../../stores/projectStore';
import { exportApi } from '../../services/ipc';

const { Title, Text } = Typography;
const CYAN = '#00d4ff';
const PURPLE = '#7c3aed';

const PRESETS = [
  { label: '横屏 1080p (推荐)', value: '1080p', resolution: '1920x1080', fps: 30, bitrate: '8M' },
  { label: '竖屏 1080p', value: '1080p_v', resolution: '1080x1920', fps: 30, bitrate: '6M' },
  { label: '横屏 4K', value: '4k', resolution: '3840x2160', fps: 60, bitrate: '20M' },
  { label: '竖屏 720p', value: '720p_v', resolution: '720x1280', fps: 30, bitrate: '4M' },
  { label: 'GIF 动图', value: 'gif', resolution: '640x360', fps: 10, bitrate: '2M' },
];

const FORMATS = ['mp4', 'mov', 'gif', 'webm'];

interface Props {
  onComplete?: () => void;
}

const ExportPanel: React.FC<Props> = ({ onComplete }) => {
  const { currentProject } = useProjectStore();
  const [preset, setPreset] = useState('1080p');
  const [format, setFormat] = useState('mp4');
  const [exporting, setExporting] = useState(false);
  const [progress, setProgress] = useState(0);
  const [done, setDone] = useState(false);
  const [outputPath, setOutputPath] = useState('');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const selectedPreset = PRESETS.find(p => p.value === preset) || PRESETS[0];

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const startExport = async () => {
    if (!currentProject) return;
    setExporting(true);
    setDone(false);
    setProgress(0);
    try {
      const result = await exportApi.start(currentProject.id, {
        format,
        resolution: selectedPreset.resolution,
        fps: selectedPreset.fps,
        bitrate: selectedPreset.bitrate,
      });
      setOutputPath(`导出任务: ${result.task_id}`);
      if (result.task_id) {
        pollRef.current = setInterval(async () => {
          try {
            const status = await exportApi.getProgress(result.task_id);
            if (status) {
              setProgress(status.progress || 0);
              if (status.status === 'completed') {
                clearInterval(pollRef.current!);
                pollRef.current = null;
                setExporting(false);
                setDone(true);
                setProgress(100);
                if (status.output_path) setOutputPath(status.output_path);
                message.success('导出完成！');
              } else if (status.status === 'failed') {
                clearInterval(pollRef.current!);
                pollRef.current = null;
                setExporting(false);
                message.error(status.message || '导出失败');
              }
            }
          } catch { /* 忽略 */ }
        }, 1000);
      }
    } catch (err: any) {
      setExporting(false);
      message.error(err?.message || '导出启动失败');
    }
  };

  const openOutputFolder = async () => {
    if (outputPath) {
      message.info('输出路径：' + outputPath);
    } else {
      message.info('输出路径：默认导出目录');
    }
  };

  if (!currentProject) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
        <div style={{ textAlign: 'center', color: '#6b7b9d' }}>
          <ExportOutlined style={{ fontSize: 48, color: '#2a3050' }} />
          <p style={{ marginTop: 12 }}>请先完成剪辑</p>
        </div>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 640, margin: '0 auto', padding: '32px 24px' }}>
      {/* 标题 */}
      <div style={{ textAlign: 'center', marginBottom: 32 }}>
        <Title level={3} style={{ color: '#e0e6ed', margin: 0 }}>🚀 导出发布</Title>
        <Text style={{ color: '#4a5a7a', fontSize: 13 }}>配置输出参数，生成最终视频</Text>
      </div>

      {!done ? (
        <>
          {/* 预设卡片 */}
          <Card style={{
            marginBottom: 16, background: 'rgba(255,255,255,0.02)',
            borderColor: 'rgba(255,255,255,0.06)', borderRadius: 12,
          }} title={<span style={{ color: '#e0e6ed' }}>📐 输出预设</span>}>
            <Select
              value={preset}
              onChange={setPreset}
              style={{ width: '100%', marginBottom: 12 }}
              variant="borderless"
              popupMatchSelectWidth={false}
              options={PRESETS.map(p => ({ label: p.label, value: p.value }))}
            />
            <div style={{
              display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8,
              padding: 12, borderRadius: 8, background: 'rgba(255,255,255,0.03)',
            }}>
              <div style={{ textAlign: 'center' }}>
                <Text style={{ color: '#6b7b9d', fontSize: 11 }}>分辨率</Text>
                <div style={{ color: '#c8d0dc', fontSize: 13, fontFamily: "'JetBrains Mono', monospace" }}>{selectedPreset.resolution}</div>
              </div>
              <div style={{ textAlign: 'center' }}>
                <Text style={{ color: '#6b7b9d', fontSize: 11 }}>帧率</Text>
                <div style={{ color: '#c8d0dc', fontSize: 13, fontFamily: "'JetBrains Mono', monospace" }}>{selectedPreset.fps}fps</div>
              </div>
              <div style={{ textAlign: 'center' }}>
                <Text style={{ color: '#6b7b9d', fontSize: 11 }}>码率</Text>
                <div style={{ color: '#c8d0dc', fontSize: 13, fontFamily: "'JetBrains Mono', monospace" }}>{selectedPreset.bitrate}</div>
              </div>
            </div>
          </Card>

          {/* 格式选择 */}
          <Card style={{
            marginBottom: 24, background: 'rgba(255,255,255,0.02)',
            borderColor: 'rgba(255,255,255,0.06)', borderRadius: 12,
          }} title={<span style={{ color: '#e0e6ed' }}>💾 输出格式</span>}>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {FORMATS.map(f => (
                <Tag
                  key={f}
                  onClick={() => setFormat(f)}
                  style={{
                    padding: '4px 16px', borderRadius: 8, fontSize: 14,
                    cursor: 'pointer', border: `1px solid ${format === f ? CYAN + '66' : 'rgba(255,255,255,0.08)'}`,
                    background: format === f ? `${CYAN}11` : 'transparent',
                    color: format === f ? CYAN : '#6b7b9d',
                    fontWeight: format === f ? 600 : 400,
                    transition: 'all 0.2s',
                  }}
                >
                  .{f}
                </Tag>
              ))}
            </div>
          </Card>

          {/* 导出按钮 */}
          <div style={{ textAlign: 'center' }}>
            {exporting ? (
              <div style={{ textAlign: 'center', maxWidth: 400, margin: '0 auto' }}>
                <Progress
                  percent={progress}
                  strokeColor={{ '0%': CYAN, '100%': PURPLE }}
                  style={{ marginBottom: 8 }}
                  trailColor="rgba(255,255,255,0.05)"
                />
                <Text style={{ color: '#4a5a7a', fontSize: 13 }}>正在导出... {progress}%</Text>
              </div>
            ) : (
              <Button
                type="primary"
                size="large"
                onClick={startExport}
                icon={<ExportOutlined />}
                style={{
                  height: 48, borderRadius: 10, padding: '0 48px',
                  background: `linear-gradient(135deg, ${CYAN}, ${PURPLE})`,
                  border: 'none', fontWeight: 600, fontSize: 15, letterSpacing: 1,
                  boxShadow: `0 0 24px ${CYAN}33`,
                }}
              >
                开始导出
              </Button>
            )}
          </div>
        </>
      ) : (
        /* 完成界面 */
        <Card style={{
          textAlign: 'center', padding: '40px 24px',
          background: 'rgba(16,185,129,0.04)',
          borderColor: 'rgba(16,185,129,0.2)', borderRadius: 16,
        }}>
          <CheckCircleFilled style={{ fontSize: 64, color: '#10b981' }} />
          <Title level={3} style={{ color: '#e0e6ed', margin: '16px 0 8px' }}>导出完成！</Title>
          <Text style={{ color: '#4a5a7a' }}>视频已成功导出</Text>
          <div style={{ marginTop: 20, display: 'flex', justifyContent: 'center', gap: 12 }}>
            <Button
              icon={<FolderOpenOutlined />}
              onClick={openOutputFolder}
              style={{ borderRadius: 8, height: 40, borderColor: `${CYAN}44`, color: CYAN }}
            >
              打开输出文件夹
            </Button>
            {onComplete && (
              <Button
                type="primary"
                onClick={onComplete}
                style={{ borderRadius: 8, height: 40, background: `linear-gradient(135deg, ${CYAN}, ${PURPLE})`, border: 'none' }}
              >
                完成
              </Button>
            )}
          </div>
        </Card>
      )}
    </div>
  );
};

export default ExportPanel;
