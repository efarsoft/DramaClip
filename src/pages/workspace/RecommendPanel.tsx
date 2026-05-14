/**
 * 方案推荐面板 — 项目工作区 Step 3
 * AI 智能推荐剪辑方案 + 备选方案
 *
 * 时长：可选配置，默认不限制（0 表示不限）
 */

import React, { useState } from 'react';
import {
  Typography, Button, Card, Space, Tag, Empty, Slider, InputNumber,
  message, Row, Col,
} from 'antd';
import {
  BulbOutlined, ThunderboltOutlined, SwapOutlined,
  CheckCircleFilled, RightOutlined, ClockCircleOutlined,
  AudioOutlined, SoundOutlined, FileTextOutlined, EllipsisOutlined,
} from '@ant-design/icons';
import { useProjectStore } from '../../stores/projectStore';
import { clipApi } from '../../services/ipc';

const { Title, Text } = Typography;
const CYAN = '#00d4ff';
const PURPLE = '#7c3aed';

// ─── 方案数据 — 三种解说/配音模式 + 全部生成 ───
const MODES = [
  {
    id: 'mode-original',
    name: '原片解说',
    desc: '提取视频情节和高光，通过截取和合并原视频进行剪辑，全程使用原声',
    type: 'original_narration',
    tags: ['原声拼接', '保留原汁原味', '适合剧情片'],
    confidence: 0.92,
  },
  {
    id: 'mode-hybrid',
    name: '交叉解说',
    desc: 'AI 生成解说词，结合原视频高光，形成混合式 AI 解说 + 原声效果',
    type: 'hybrid_narration',
    tags: ['AI 解说', '原声混音', '适合解说类'],
    confidence: 0.88,
  },
  {
    id: 'mode-full',
    name: '全片解说',
    desc: 'AI 生成全部解说文案并配音，不使用原声，纯 AI 旁白风格',
    type: 'full_narration',
    tags: ['全 AI 配音', '几分钟看完', '适合速览'],
    confidence: 0.85,
  },
  {
    id: 'mode-all',
    name: '全部生成',
    desc: '一次性生成以上三种模式的剪辑结果，对比择优或同时分发',
    type: 'all_narrations',
    tags: ['一键三连', '批量输出', '效率最高'],
    confidence: 0.95,
  },
];

interface Props {
  onNext?: () => void;
}

const RecommendPanel: React.FC<Props> = ({ onNext }) => {
  const { currentProject } = useProjectStore();
  const [selected, setSelected] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  // 0 表示不限时长
  const [targetDuration, setTargetDuration] = useState<number>(0);

  const handleApply = async () => {
    if (!selected || !currentProject) return;
    setApplying(true);
    try {
      const plan = MODES.find(p => p.id === selected)!;
      await clipApi.execute(currentProject.id, plan.type, {
        // 传 0 或 None 到后端，后端接收 None 表示不限制时长
        output_duration: targetDuration > 0 ? targetDuration : undefined,
      });
      message.success('方案已应用，进入剪辑阶段');
      onNext?.();
    } catch (e: any) {
      message.error(e?.message || '应用方案失败');
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
      {/* ─── 头部 ─── */}
      <div style={{ marginBottom: 28, textAlign: 'center' }}>
        <Title level={4} style={{ color: '#e8edff', marginBottom: 8 }}>
          <BulbOutlined style={{ marginRight: 10, color: '#fbbf24' }} />
          AI 方案推荐
        </Title>
        <Text style={{ color: '#4a5a7a', fontSize: 13 }}>
          AI 根据分析结果为 "{currentProject.name}" 生成了以下剪辑方案
        </Text>
      </div>

      {/* ─── 方案卡片列表 ─── */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {MODES.map((plan) => (
          <Card
            key={plan.id}
            hoverable
            onClick={() => setSelected(plan.id)}
            style={{
              borderRadius: 14,
              background:
                selected === plan.id
                  ? `linear-gradient(135deg, ${CYAN}11, ${PURPLE}11)`
                  : 'rgba(255,255,255,0.02)',
              border:
                selected === plan.id
                  ? `1.5px solid ${CYAN}66`
                  : '1px solid rgba(255,255,255,0.06)',
              cursor: 'pointer',
              transition: 'all 0.3s',
              position: 'relative',
              overflow: 'hidden',
            }}
            bodyStyle={{ padding: '20px 24px' }}
          >
            {/* 选中标记 */}
            {selected === plan.id && (
              <CheckCircleFilled
                style={{
                  position: 'absolute', top: 14, right: 14,
                  color: CYAN, fontSize: 20,
                }}
              />
            )}

            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
              {/* 图标 */}
              <div
                style={{
                  width: 44, height: 44, borderRadius: 12,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 22,
                  background:
                    selected === plan.id
                      ? `linear-gradient(135deg, ${CYAN}22, ${PURPLE}22)`
                      : 'rgba(255,255,255,0.04)',
                  flexShrink: 0,
                }}
              >
                {plan.id === 'mode-original' ? (
                  <SoundOutlined style={{ color: CYAN }} />
                ) : plan.id === 'mode-hybrid' ? (
                  <SwapOutlined style={{ color: '#f59e0b' }} />
                ) : plan.id === 'mode-full' ? (
                  <AudioOutlined style={{ color: '#f472b6' }} />
                ) : (
                  <EllipsisOutlined style={{ color: '#a78bfa' }} />
                )}
              </div>

              {/* 内容 */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                  <Text strong style={{ color: '#e8edff', fontSize: 16 }}>
                    {plan.name}
                  </Text>
                  <Tag
                    color="cyan"
                    style={{
                      borderRadius: 12, fontSize: 11, lineHeight: '20px',
                      padding: '0 10px', border: 'none', opacity: 0.8,
                    }}
                  >
                    {plan.type === 'original_narration' ? '原声' : plan.type === 'hybrid_narration' ? '混音' : plan.type === 'full_narration' ? 'AI配音' : '一键三连'}
                  </Tag>
                </div>

                <Text style={{ color: '#8892a4', display: 'block', marginBottom: 10, lineHeight: 1.6 }}>
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
                  <span style={{
                    marginLeft: 'auto', fontSize: 12, color: '#4a5a7a',
                    fontFamily: "'JetBrains Mono', monospace",
                  }}>
                    匹配度 {Math.round(plan.confidence * 100)}%
                  </span>
                </div>
              </div>
            </div>
          </Card>
        ))}
      </div>

      {/* ─── 时长配置（可选） ─── */}
      <Card
        style={{
          marginTop: 20, borderRadius: 14,
          background: 'rgba(255,255,255,0.02)',
          border: '1px solid rgba(255,255,255,0.06)',
        }}
        bodyStyle={{ padding: '16px 24px' }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <ClockCircleOutlined style={{ color: CYAN, fontSize: 18 }} />
          <Text style={{ color: '#8892a4', fontSize: 14, whiteSpace: 'nowrap' }}>输出时长</Text>
          <div style={{ flex: 1, minWidth: 180, padding: '0 12px' }}>
            <Slider
              min={0}
              max={300}
              step={5}
              value={targetDuration}
              onChange={setTargetDuration}
              tooltip={{ formatter: (v: number | undefined) => !v || v === 0 ? '不限' : `${v}秒` }}
              trackStyle={{ background: `linear-gradient(90deg, ${CYAN}, ${PURPLE})` }}
              handleStyle={{ borderColor: CYAN }}
            />
          </div>
          <InputNumber
            min={0}
            max={300}
            step={5}
            value={targetDuration}
            onChange={v => setTargetDuration(v ?? 0)}
            style={{ width: 80, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)', color: '#e8edff' }}
            formatter={v => v === 0 ? '不限' : `${v}s`}
            parser={v => parseInt(v?.replace(/[^0-9]/g, '') || '0', 10)}
          />
          <Text style={{ color: '#4a5a7a', fontSize: 12 }}>0=不限</Text>
        </div>
      </Card>

      {/* ─── 操作按钮 ─── */}
      <div style={{ display: 'flex', justifyContent: 'center', gap: 16, marginTop: 28 }}>
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
