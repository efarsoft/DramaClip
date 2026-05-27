/**
 * 方案推荐面板 — 项目工作区 Step 3
 * AI 智能推荐剪辑方案 + 备选方案
 *
 * 时长：可选配置，默认不限制（0 表示不限）
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
  Typography, Button, Card, Space, Tag, Empty, Slider, InputNumber,
  App, Skeleton, Alert, Progress, Spin, Select
} from 'antd';
import {
  BulbOutlined, ThunderboltOutlined, ClockCircleOutlined,
  AudioOutlined, SoundOutlined, FileTextOutlined, EllipsisOutlined,
  CheckCircleFilled, RightOutlined, LoadingOutlined,
} from '@ant-design/icons';
import { useProjectStore } from '../../stores/projectStore';
import { useTaskQueueStore } from '../../stores/taskQueueStore';
import { clipApi, type ClipRecommendation } from '../../services/ipc';

const { Title, Text } = Typography;
const CYAN = '#00d4ff';
const PURPLE = '#7c3aed';

const PRESETS = [
  { label: '16:9 横屏 (1080p 推荐)', value: '1080p', resolution: '1920x1080', fps: 30, bitrate: '8M' },
  { label: '9:16 竖屏 (1080p)', value: '1080p_v', resolution: '1080x1920', fps: 30, bitrate: '6M' },
];

// ─── 方案数据 — 三种解说/配音模式 + 全部生成 ───
const ALL_MODES = [
  {
    id: 'mode-original',
    name: '原片解说',
    desc: '提取视频情节和高光，通过截取和合并原视频进行剪辑，全程使用原声',
    type: 'original_narration',
    tags: ['原声拼接', '保留原汁原味', '适合剧情片'],
    icon: <SoundOutlined style={{ color: CYAN }} />,
    priority: 0,
  },
  {
    id: 'mode-hybrid',
    name: '交叉解说',
    desc: 'AI 生成解说词，结合原视频高光，形成混合式 AI 解说 + 原声效果',
    type: 'hybrid_narration',
    tags: ['AI 解说', '原声混音', '适合解说类'],
    icon: <ThunderboltOutlined style={{ color: '#f59e0b' }} />,
    priority: 1,
  },
  {
    id: 'mode-full',
    name: '全片解说',
    desc: 'AI 生成全部解说文案并配音，不使用原声，纯 AI 旁白风格',
    type: 'full_narration',
    tags: ['全 AI 配音', '几分钟看完', '适合速览'],
    icon: <AudioOutlined style={{ color: '#f472b6' }} />,
    priority: 2,
  },
  {
    id: 'mode-all',
    name: '全部生成',
    desc: '一次性生成以上三种模式的剪辑结果，对比择优或同时分发',
    type: 'all_narrations',
    tags: ['一键三连', '批量输出', '效率最高'],
    icon: <EllipsisOutlined style={{ color: '#a78bfa' }} />,
    priority: 3,
  },
];

interface Props {
  onNext?: () => void;
}

const RecommendPanel: React.FC<Props> = ({ onNext }) => {
  const { message } = App.useApp();
  const { currentProject, selectedEpisodeIds, currentVideos } = useProjectStore();
  const [selected, setSelected] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [recommendation, setRecommendation] = useState<ClipRecommendation | null>(null);
  const [filteredModes, setFilteredModes] = useState<typeof ALL_MODES>([]);
  // 0 表示不限时长
  const [targetDuration, setTargetDuration] = useState<number>(0);
  const [activeClipTaskId, setActiveClipTaskId] = useState<string | null>(null);
  
  const [preset, setPreset] = useState(() => localStorage.getItem('dramaclip-export-preset') || '1080p');
  const selectedPreset = PRESETS.find(p => p.value === preset) || PRESETS[0];

  useEffect(() => {
    localStorage.setItem('dramaclip-export-preset', preset);
  }, [preset]);

  // 获取当前活跃的自动剪辑任务（自适应后端 ID 动态重写）
  const activeClipTask = useTaskQueueStore(s => {
    if (!activeClipTaskId) return undefined;
    const matched = s.tasks.find(t => t.id === activeClipTaskId);
    if (matched) return matched;

    // 若本地生成的临时 ID 被后端真实 Task ID 重写，则通过项目ID及类型定位最新的剪辑任务
    return s.tasks
      .filter(t => t.type === 'clip' && t.projectId === currentProject?.id)
      .sort((a, b) => b.createdAt - a.createdAt)[0];
  });

  // 加载推荐方案
  const loadRecommendation = useCallback(async () => {
    if (!currentProject) return;
    setLoading(true);
    try {
      const rec = await clipApi.recommend(currentProject.id);
      setRecommendation(rec);

      // 根据推荐排序并过滤模式
      const sortedModes = [...ALL_MODES].sort((a, b) => a.priority - b.priority);
      if (rec.recommended_modes && rec.recommended_modes.length > 0) {
        // 按推荐顺序排列，只显示推荐的模式
        const modeEntries: [string, typeof ALL_MODES[0]][] = [];
        for (const type of rec.recommended_modes) {
          const mode = ALL_MODES.find(m => m.type === type);
          if (mode) modeEntries.push([type, mode]);
        }
        const filtered = modeEntries.map(([, mode]) => mode);
        setFilteredModes(filtered);
      } else {
        setFilteredModes(sortedModes);
      }

      // 自动选中推荐方案
      if (rec.recommended_scheme) {
        setSelected(rec.recommended_scheme);
      }
    } catch (e: any) {
      console.error('Failed to load recommendation:', e);
      message.error('加载推荐方案失败');
      setFilteredModes(ALL_MODES);
    } finally {
      setLoading(false);
    }
  }, [currentProject]);

  useEffect(() => {
    loadRecommendation();
  }, [loadRecommendation]);

  // 监听并追踪自动剪辑进度，完成后自动跳转到 Step 4
  useEffect(() => {
    if (!activeClipTask) return;
    if (activeClipTask.status === 'completed') {
      setApplying(false);
      message.success('🎉 AI 智能剪辑已自动合成完成！进入导出发布阶段。');
      onNext?.();
    } else if (activeClipTask.status === 'failed') {
      setApplying(false);
      setActiveClipTaskId(null);
      message.error(`❌ AI 智能剪辑失败: ${activeClipTask.error || '合成超时，请重新应用方案！'}`);
    }
  }, [activeClipTask?.status, activeClipTask?.error, onNext]);

  const handleApply = async () => {
    if (!selected || !currentProject) return;
    setApplying(true);
    try {
      const plan = ALL_MODES.find(p => p.id === selected)!;
      useProjectStore.getState().setClipScheme(plan.type);
      
      // 1. 聚合所有已选择且已完成分析的视频的高光片段（保持勾选顺序与虚拟连续时间轴一致）
      const allTasks = useTaskQueueStore.getState().tasks;
      const aggregatedHighlights: any[] = [];

      for (const episodeId of selectedEpisodeIds) {
        // 寻找该视频对应的已完成分析任务
        const matchedTask = allTasks.find(t => {
          const ids = t.params?.episode_ids as string[] | undefined;
          return t.type === 'analyze' && t.status === 'completed' && ids && ids.includes(episodeId);
        });

        if (!matchedTask) continue;

        const results = matchedTask.results as any;
        const highlights = results?.highlights ?? [];
        const videoMeta = currentVideos.find(v => v.id === episodeId);

        highlights.forEach((h: any, i: number) => {
          aggregatedHighlights.push({
            ...h,
            id: `${matchedTask.id}-${h.id || h.segment_id || i}`,
            video_path: h.video_path || videoMeta?.path,
          });
        });
      }

      if (aggregatedHighlights.length === 0) {
        throw new Error('未检测到任何已完成视频的 AI 分析高光片段，请返回上一步重新分析！');
      }

      // 2. 自动入队剪辑拼接任务，100% 流程自动化，无需任何人工选取
      const taskId = useTaskQueueStore.getState().enqueue('clip', currentProject.id, {
        project_id: currentProject.id,
        scheme: plan.type,
        params: {
          segments: aggregatedHighlights,
          clip_mode: 'highlight',
          target_duration: targetDuration,
        },
      });

      setActiveClipTaskId(taskId);
      message.loading({ content: '已自动为您创建 AI 智能剪辑合成任务，正在拼装生成...', duration: 2 });
    } catch (e: any) {
      message.error(e?.message || '自动剪辑方案应用失败');
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

  // 检查是否有正在运行或排队中的分析任务
  const isAnalyzing = useTaskQueueStore.getState().tasks.some(t => 
    t.type === 'analyze' && (t.status === 'running' || t.status === 'queued') && t.projectId === currentProject?.id
  );

  if (isAnalyzing) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', minHeight: 480, padding: '40px 24px' }}>
        <Card style={{
          width: '100%',
          maxWidth: 520,
          background: 'rgba(255, 255, 255, 0.01)',
          borderColor: 'rgba(0, 212, 255, 0.12)',
          borderRadius: 16,
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.4)',
          textAlign: 'center',
        }}
        styles={{ body: { padding: '40px 32px' } }}
        >
          <div style={{ marginBottom: 24 }}>
            <Spin indicator={<LoadingOutlined style={{ fontSize: 44, color: CYAN }} spin />} />
          </div>
          <Title level={4} style={{ color: '#e8edff', margin: '0 0 12px 0', fontWeight: 600 }}>
            🤖 AI 智能内容分析正在进行中...
          </Title>
          <Text style={{ color: '#8892a4', fontSize: 13, display: 'block', lineHeight: 1.6, marginBottom: 20 }}>
            系统正对您导入的视频进行深度多维分析（包括提取台词、识别说话人、分析情绪曲线与高光打分）。<br />
            请通过顶部步骤条返回 <b>【Step 2: AI 分析】</b>，等待分析流程 100% 运行完毕后，再在此处生成或应用剪辑方案。
          </Text>
        </Card>
      </div>
    );
  }

  const episodeTypeLabel = recommendation?.episode_type === 'multi' ? '多集' :
    recommendation?.episode_type === 'single' ? '单集' : '未识别';

  return (
    <div style={{ maxWidth: 760, margin: '0 auto', padding: '32px 24px', position: 'relative', minHeight: '100%' }}>
      {/* ─── 头部 ─── */}
      <div style={{ marginBottom: 28, textAlign: 'center' }}>
        <Title level={4} style={{ color: '#e8edff', marginBottom: 8 }}>
          <BulbOutlined style={{ marginRight: 10, color: '#fbbf24' }} />
          AI 方案推荐
        </Title>
        <Text style={{ color: '#4a5a7a', fontSize: 13 }}>
          AI 根据分析结果为 "{currentProject.name}" 生成了以下剪辑方案
        </Text>
        {recommendation && (
          <div style={{ marginTop: 8 }}>
            <Tag color="cyan" style={{ borderRadius: 12, marginRight: 8 }}>
              {episodeTypeLabel}
            </Tag>
            <Tag color="purple" style={{ borderRadius: 12 }}>
              {recommendation.episode_count} 集
            </Tag>
          </div>
        )}
      </div>

      {/* ─── 推荐说明 ─── */}
      {recommendation && recommendation.reasons.length > 0 && (
        <Alert
          type="info"
          showIcon
          icon={<BulbOutlined style={{ color: '#fbbf24' }} />}
          message={
            <span>
              <Text strong style={{ color: '#e8edff' }}>AI 推荐理由：</Text>
              <Text style={{ color: '#8892a4', marginLeft: 8 }}>
                {recommendation.reasons.join('；')}
              </Text>
            </span>
          }
          style={{ marginBottom: 24, borderRadius: 12, background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.06)' }}
        />
      )}

      {/* ─── 方案卡片列表 ─── */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {loading ? (
          <Skeleton active paragraph={{ rows: 4 }} />
        ) : (
          filteredModes.map((plan) => {
            const isSelected = selected === plan.id;
            const isRecommended = recommendation?.recommended_scheme === plan.type;
            return (
              <Card
                key={plan.id}
                hoverable
                onClick={() => setSelected(plan.id)}
                style={{
                  borderRadius: 14,
                  background:
                    isSelected
                      ? `linear-gradient(135deg, ${CYAN}11, ${PURPLE}11)`
                      : isRecommended ? 'rgba(251,191,36,0.04)' : 'rgba(255,255,255,0.02)',
                  border:
                    isSelected
                      ? `1.5px solid ${CYAN}66`
                      : isRecommended ? '1.5px dashed #fbbf2444' : '1px solid rgba(255,255,255,0.06)',
                  cursor: 'pointer',
                  transition: 'all 0.3s',
                  position: 'relative',
                  overflow: 'hidden',
                }}
                styles={{ body: { padding: '20px 24px' } }}
              >
                {/* 选中标记 */}
                {isSelected && (
                  <CheckCircleFilled
                    style={{
                      position: 'absolute', top: 14, right: 14,
                      color: CYAN, fontSize: 20,
                    }}
                  />
                )}
                {/* 推荐标记 */}
                {isRecommended && !isSelected && (
                  <div style={{
                    position: 'absolute', top: 14, right: 14,
                    padding: '2px 10px', borderRadius: 12, fontSize: 11,
                    background: 'rgba(251,191,36,0.1)', color: '#fbbf24',
                    border: '1px solid #fbbf2444',
                  }}>
                    AI 推荐
                  </div>
                )}

                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
                  {/* 图标 */}
                  <div
                    style={{
                      width: 44, height: 44, borderRadius: 12,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 22,
                      background:
                        isSelected
                          ? `linear-gradient(135deg, ${CYAN}22, ${PURPLE}22)`
                          : 'rgba(255,255,255,0.04)',
                      flexShrink: 0,
                    }}
                  >
                    {plan.icon}
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
                    </div>
                  </div>
                </div>
              </Card>
            );
          })
        )}
      </div>

      {/* ─── 时长配置（可选） ─── */}
      <Card
        style={{
          marginTop: 20, borderRadius: 14,
          background: 'rgba(255,255,255,0.02)',
          border: '1px solid rgba(255,255,255,0.06)',
        }}
        styles={{ body: { padding: '16px 24px' } }}
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

      {/* ─── 输出预设（横竖屏选择） ─── */}
      <Card
        style={{
          marginTop: 14, borderRadius: 14,
          background: 'rgba(255,255,255,0.02)',
          border: '1px solid rgba(255,255,255,0.06)',
        }}
        styles={{ body: { padding: '16px 24px' } }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 16 }}>📐</span>
            <Text style={{ color: '#8892a4', fontSize: 14, whiteSpace: 'nowrap' }}>输出预设</Text>
          </div>
          <Select
            value={preset}
            onChange={setPreset}
            style={{ width: 220, background: 'rgba(255,255,255,0.04)', borderRadius: 6 }}
            variant="borderless"
            popupMatchSelectWidth={false}
            options={PRESETS.map(p => ({ label: p.label, value: p.value }))}
          />
          <div style={{
            display: 'flex', gap: 16, padding: '6px 16px', borderRadius: 8,
            background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.04)'
          }}>
            <div>
              <Text style={{ color: '#6b7b9d', fontSize: 11, marginRight: 6 }}>分辨率</Text>
              <Text style={{ color: '#c8d0dc', fontSize: 12, fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 }}>{selectedPreset.resolution}</Text>
            </div>
            <div>
              <Text style={{ color: '#6b7b9d', fontSize: 11, marginRight: 6 }}>帧率</Text>
              <Text style={{ color: '#c8d0dc', fontSize: 12, fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 }}>{selectedPreset.fps}fps</Text>
            </div>
          </div>
        </div>
      </Card>

      {/* ─── 操作按钮 ─── */}
      <div style={{ display: 'flex', justifyContent: 'center', gap: 16, marginTop: 28 }}>
        <Button
          type="primary"
          size="large"
          disabled={!selected || loading}
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

      {/* ─── 智能剪辑高光自动拼接 glassmorphism 加载遮罩 ─── */}
      {activeClipTask && (activeClipTask.status === 'running' || activeClipTask.status === 'queued') && (
        <div style={{
          position: 'absolute',
          top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(6, 10, 23, 0.85)',
          backdropFilter: 'blur(16px)',
          zIndex: 1000,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '40px 24px',
          borderRadius: 14,
          border: '1px solid rgba(255, 255, 255, 0.05)',
        }}>
          {/* Glassmorphic card */}
          <Card style={{
            width: '100%',
            maxWidth: 480,
            background: 'rgba(255, 255, 255, 0.01)',
            borderColor: 'rgba(255, 255, 255, 0.06)',
            borderRadius: 16,
            boxShadow: '0 8px 32px rgba(0, 0, 0, 0.4)',
            textAlign: 'center',
          }}
          styles={{ body: { padding: '40px 32px' } }}
          >
            <div style={{ position: 'relative', display: 'inline-block', marginBottom: 24 }}>
              <Spin indicator={<LoadingOutlined style={{ fontSize: 48, color: CYAN }} spin />} />
              <div style={{
                position: 'absolute', top: '50%', left: '50%',
                transform: 'translate(-50%, -50%)',
                fontSize: 20,
              }}>✨</div>
            </div>
            
            <Title level={4} style={{ color: '#e8edff', margin: '0 0 8px 0', fontWeight: 600 }}>
              AI 智能剪辑合成中
            </Title>
            <Text style={{ color: '#8892a4', fontSize: 13, display: 'block', marginBottom: 24 }}>
              {activeClipTask.phase === 'clipping' ? '正在拼接和渲染高光视频片段...' : 
               activeClipTask.phase === 'audio' ? '正在融合背景音乐与人声对白...' :
               activeClipTask.message || '系统正在自动挑选并合成高光片段，无需人工干预...'}
            </Text>

            <Progress
              percent={activeClipTask.progress}
              strokeColor={{ '0%': CYAN, '100%': PURPLE }}
              trailColor="rgba(255, 255, 255, 0.05)"
              showInfo={false}
              style={{ marginBottom: 12 }}
            />
            
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ color: '#4a5a7a', fontSize: 12 }}>已跑通 AI 大模型高光打分方案</span>
              <span style={{ color: CYAN, fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, fontSize: 15 }}>
                {activeClipTask.progress}%
              </span>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
};

export default RecommendPanel;
