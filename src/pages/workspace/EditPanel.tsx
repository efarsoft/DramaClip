/**
 * 智能剪辑面板 — 项目工作区 Step 4
 * 展示片段列表，支持预览与调整
 */

import React, { useState } from 'react';
import { Typography, Button, Card, Space, Tag, Slider, Empty, Switch, message } from 'antd';
import {
  ScissorOutlined,
  SoundOutlined,
  FileTextOutlined,
  SwapOutlined,
  PlayCircleOutlined,
  CheckCircleFilled,
  ArrowRightOutlined,
} from '@ant-design/icons';
import { useProjectStore } from '../../stores/projectStore';
import { clipApi } from '../../services/ipc';

const { Title, Text } = Typography;
const CYAN = '#00d4ff';
const PURPLE = '#7c3aed';

// ─── Mock 片段数据 ───
const MOCK_SEGMENTS = [
  { id: 's1', start: 0, end: 3.5, label: '开场', desc: '角色1出场', emotion: 'neutral', duration: 3.5 },
  { id: 's2', start: 4.0, end: 8.2, label: '对话', desc: '角色1与角色2对话', emotion: 'joy', duration: 4.2 },
  { id: 's3', start: 9.5, end: 15.0, label: '高潮', desc: '剧情转折点', emotion: 'anger', duration: 5.5 },
  { id: 's4', start: 16.0, end: 20.0, label: '解局', desc: '冲突化解', emotion: 'surprise', duration: 4.0 },
];

interface Props {
  onNext: () => void;
}

const EditPanel: React.FC<Props> = ({ onNext }) => {
  const { currentProject } = useProjectStore();
  const [segments, setSegments] = useState(MOCK_SEGMENTS);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set(segments.map(s => s.id)));

  const toggleSelect = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleFinish = async () => {
    if (!currentProject) return;
    try {
      await clipApi.preview(currentProject.id, Array.from(selectedIds).join(','));
      message.success('剪辑片段已确认');
      onNext();
    } catch (err: any) {
      message.error(err?.message || '操作失败');
    }
  };

  if (!currentProject) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
        <Empty description={<span style={{ color: '#6b7b9d' }}>请先应用剪辑方案</span>} image={Empty.PRESENTED_IMAGE_SIMPLE} />
      </div>
    );
  }

  const EMOTION_COLORS: Record<string, string> = {
    neutral: '#6b7b9d', joy: '#10b981', anger: '#ef4444', surprise: '#f59e0b', sad: '#6366f1',
  };

  const totalDuration = segments
    .filter(s => selectedIds.has(s.id))
    .reduce((acc, s) => acc + s.duration, 0);

  return (
    <div style={{ maxWidth: 760, margin: '0 auto', padding: '32px 24px' }}>
      {/* ─── 标题 ─── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
        <div>
          <Title level={3} style={{ color: '#e0e6ed', margin: 0 }}>
            ✂️ 智能剪辑
          </Title>
          <Text style={{ color: '#4a5a7a', fontSize: 13 }}>
            选择要保留的片段，调整顺序和参数
          </Text>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ color: CYAN, fontSize: 24, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>
            {totalDuration.toFixed(1)}s
          </div>
          <Text style={{ color: '#4a5a7a', fontSize: 12 }}>已选片段总时长</Text>
        </div>
      </div>

      {/* ─── 片段列表 ─── */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 24 }}>
        {segments.map((seg, idx) => {
          const selected = selectedIds.has(seg.id);
          return (
            <div
              key={seg.id}
              onClick={() => toggleSelect(seg.id)}
              style={{
                display: 'flex', alignItems: 'center', gap: 16,
                padding: '16px 20px', borderRadius: 12,
                background: selected ? `linear-gradient(135deg, ${CYAN}08, ${PURPLE}08)` : 'rgba(255,255,255,0.02)',
                border: selected ? `1px solid ${CYAN}44` : '1px solid rgba(255,255,255,0.05)',
                cursor: 'pointer', transition: 'all 0.25s',
                opacity: selected ? 1 : 0.45,
              }}
              onMouseEnter={e => { if (selected) e.currentTarget.style.borderColor = `${CYAN}88`; }}
              onMouseLeave={e => { if (selected) e.currentTarget.style.borderColor = `${CYAN}44`; }}
            >
              {/* 序号 */}
              <span style={{
                width: 26, height: 26, borderRadius: 8, display: 'flex',
                alignItems: 'center', justifyContent: 'center',
                background: `rgba(255,255,255,0.06)`, color: '#4a5a7a',
                fontSize: 12, fontWeight: 600, fontFamily: "'JetBrains Mono', monospace",
              }}>{idx + 1}</span>

              {/* 时间 */}
              <span style={{
                color: '#6b7b9d', fontSize: 13, fontFamily: "'JetBrains Mono', monospace",
                minWidth: 100,
              }}>
                {seg.start.toFixed(1)}s → {seg.end.toFixed(1)}s
              </span>

              {/* 标签 */}
              <div style={{ flex: 1 }}>
                <Text strong style={{ color: '#d0d6e0', fontSize: 14 }}>{seg.label}</Text>
                <Text style={{ color: '#4a5a7a', fontSize: 12, marginLeft: 8 }}>{seg.desc}</Text>
              </div>

              {/* 情绪标签 */}
              <div style={{
                padding: '2px 10px', borderRadius: 20, fontSize: 12,
                background: `${EMOTION_COLORS[seg.emotion] || '#6b7b9d'}22`,
                color: EMOTION_COLORS[seg.emotion] || '#6b7b9d',
                border: `1px solid ${EMOTION_COLORS[seg.emotion] || '#6b7b9d'}33`,
              }}>
                {seg.emotion}
              </div>

              {/* 选择指示器 */}
              <div style={{
                width: 20, height: 20, borderRadius: 6,
                border: `2px solid ${selected ? CYAN : '#2a3050'}`,
                background: selected ? CYAN : 'transparent',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                transition: 'all 0.2s',
              }}>
                {selected && <CheckCircleFilled style={{ color: '#0a0e1a', fontSize: 12 }} />}
              </div>
            </div>
          );
        })}
      </div>

      {/* ─── 附加选项 ─── */}
      <Card style={{
        background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.06)',
        borderRadius: 12, marginBottom: 24,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <Space>
            <SoundOutlined style={{ color: CYAN }} />
            <Text style={{ color: '#c8d0dc' }}>AI 旁白解说</Text>
          </Space>
          <Switch defaultChecked size="small" style={{ background: '#2a3050' }} />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Space>
            <FileTextOutlined style={{ color: PURPLE }} />
            <Text style={{ color: '#c8d0dc' }}>自动字幕</Text>
          </Space>
          <Switch defaultChecked size="small" style={{ background: '#2a3050' }} />
        </div>
      </Card>

      {/* ─── 确认按钮 ─── */}
      <div style={{ textAlign: 'center' }}>
        <Button
          type="primary"
          size="large"
          onClick={handleFinish}
          style={{
            height: 48, borderRadius: 10, padding: '0 40px',
            background: `linear-gradient(135deg, ${CYAN}, ${PURPLE})`,
            border: 'none', fontWeight: 600, fontSize: 15, letterSpacing: 1,
            boxShadow: `0 0 24px ${CYAN}33`,
          }}
          disabled={selectedIds.size === 0}
        >
          <Space>
            确认剪辑
            <ArrowRightOutlined />
          </Space>
        </Button>
      </div>
    </div>
  );
};

export default EditPanel;
