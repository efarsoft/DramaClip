/**
 * 方案推荐面板 — 项目工作区 Step 3
 * AI 智能推荐剪辑方案 + 备选方案
 */

import React, { useState } from 'react';
import { Typography, Button, Card, Space, Tag, Empty, Descriptions, message } from 'antd';
import {
  BulbOutlined,
  ThunderboltOutlined,
  SwapOutlined,
  CheckCircleFilled,
  RightOutlined,
} from '@ant-design/icons';
import { useProjectStore } from '../../stores/projectStore';
import { clipApi } from '../../services/ipc';

const { Title, Text } = Typography;
const CYAN = '#00d4ff';
const PURPLE = '#7c3aed';

// ─── Mock 方案数据 ───
const MOCK_PLANS = [
  {
    id: 'plan-a',
    name: '智能精简版',
    desc: '自动提取高光片段，保留核心剧情，生成 30-60 秒精华短片',
    type: 'highlight',
    duration: '30-60s',
    tags: ['高光提取', '自动剪辑', '适合短视频'],
    confidence: 0.92,
  },
  {
    id: 'plan-b',
    name: '剧情完整版',
    desc: '保留完整叙事结构，配以 AI 旁白解说，生成 3-5 分钟解说视频',
    type: 'narrative',
    duration: '3-5min',
    tags: ['旁白解说', '完整剧情', '适合B站'],
    confidence: 0.87,
  },
  {
    id: 'plan-c',
    name: '混剪燃向版',
    desc: '提取高燃/高情绪片段，配合快节奏转场和背景音乐',
    type: 'montage',
    duration: '1-2min',
    tags: ['混剪', '高燃', '节奏感强'],
    confidence: 0.78,
  },
];

interface Props {
  onNext: () => void;
}

const RecommendPanel: React.FC<Props> = ({ onNext }) => {
  const { currentProject } = useProjectStore();
  const [selected, setSelected] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  const handleApply = async () => {
    if (!selected || !currentProject) return;
    setApplying(true);
    try {
      const plan = MOCK_PLANS.find(p => p.id === selected)!;
      await clipApi.execute(currentProject.id, plan.type, {});
      message.success('方案已应用，进入剪辑阶段');
      onNext();
    } catch (err: any) {
      message.error(err?.message || '方案应用失败');
    } finally {
      setApplying(false);
    }
  };

  if (!currentProject) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
        <Empty description={<span style={{ color: '#6b7b9d' }}>请先完成 AI 分析</span>} image={Empty.PRESENTED_IMAGE_SIMPLE} />
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 760, margin: '0 auto', padding: '32px 24px' }}>
      {/* ─── 标题 ─── */}
      <div style={{ marginBottom: 28 }}>
        <Title level={3} style={{ color: '#e0e6ed', margin: 0 }}>
          ✨ 智能方案推荐
        </Title>
        <Text style={{ color: '#4a5a7a', fontSize: 13 }}>
          AI 根据分析结果为 "{currentProject.name}" 生成了以下剪辑方案
        </Text>
      </div>

      {/* ─── 方案卡片列表 ─── */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {MOCK_PLANS.map((plan, idx) => (
          <div
            key={plan.id}
            onClick={() => setSelected(plan.id)}
            style={{
              padding: '24px', borderRadius: 14,
              background: selected === plan.id
                ? `linear-gradient(135deg, ${CYAN}11, ${PURPLE}11)`
                : 'rgba(255,255,255,0.02)',
              border: selected === plan.id
                ? `1.5px solid ${CYAN}66`
                : '1px solid rgba(255,255,255,0.06)',
              cursor: 'pointer',
              transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
              position: 'relative',
              overflow: 'hidden',
            }}
            onMouseEnter={e => {
              if (selected !== plan.id) {
                e.currentTarget.style.borderColor = `${CYAN}44`;
                e.currentTarget.style.background = 'rgba(255,255,255,0.04)';
              }
            }}
            onMouseLeave={e => {
              if (selected !== plan.id) {
                e.currentTarget.style.borderColor = 'rgba(255,255,255,0.06)';
                e.currentTarget.style.background = 'rgba(255,255,255,0.02)';
              }
            }}
          >
            {/* 选中标记 */}
            {selected === plan.id && (
              <div style={{
                position: 'absolute', top: 12, right: 16,
                color: CYAN, fontSize: 20,
              }}>
                <CheckCircleFilled />
              </div>
            )}

            {/* 序号 */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12,
            }}>
              <span style={{
                width: 28, height: 28, borderRadius: 8,
                background: `linear-gradient(135deg, ${CYAN}44, ${PURPLE}44)`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                color: '#fff', fontSize: 13, fontWeight: 700,
              }}>{idx + 1}</span>
              <Title level={4} style={{ color: '#e0e6ed', margin: 0, flex: 1 }}>{plan.name}</Title>
              <Tag style={{
                borderRadius: 6, border: 'none', padding: '2px 12px',
                background: `linear-gradient(135deg, ${CYAN}22, ${CYAN}11)`,
                color: CYAN, fontSize: 12, fontFamily: "'JetBrains Mono', monospace",
              }}>
                {plan.duration}
              </Tag>
            </div>

            <Text style={{ color: '#8892a4', display: 'block', marginBottom: 12, lineHeight: 1.6 }}>
              {plan.desc}
            </Text>

            {/* 标签 */}
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {plan.tags.map(tag => (
                <span key={tag} style={{
                  padding: '2px 12px', borderRadius: 20, fontSize: 12,
                  background: 'rgba(255,255,255,0.05)',
                  color: '#6b7b9d', border: '1px solid rgba(255,255,255,0.06)',
                }}>
                  {tag}
                </span>
              ))}
              {/* 置信度 */}
              <span style={{
                marginLeft: 'auto', fontSize: 12, color: '#4a5a7a',
                fontFamily: "'JetBrains Mono', monospace",
              }}>
                匹配度 {Math.round(plan.confidence * 100)}%
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* ─── 操作按钮 ─── */}
      <div style={{ display: 'flex', justifyContent: 'center', gap: 16, marginTop: 32 }}>
        <Button
          type="primary"
          size="large"
          disabled={!selected}
          loading={applying}
          onClick={handleApply}
          style={{
            height: 48, borderRadius: 10, padding: '0 40px',
            background: selected ? `linear-gradient(135deg, ${CYAN}, ${PURPLE})` : undefined,
            border: 'none', fontWeight: 600, fontSize: 15, letterSpacing: 1,
            boxShadow: selected ? `0 0 24px ${CYAN}33` : undefined,
          }}
        >
          <Space>
            {applying ? '应用中...' : '应用此方案'}
            <RightOutlined />
          </Space>
        </Button>
      </div>
    </div>
  );
};

export default RecommendPanel;
