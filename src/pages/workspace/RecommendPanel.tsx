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
    desc: '最还原的原声高燃混剪，情绪最直接，故事最纯粹',
    type: 'original_narration',
    tags: ['原声最燃', '情绪最强'],
    icon: <SoundOutlined style={{ color: CYAN }} />,
    priority: 0,
  },
  {
    id: 'mode-hybrid',
    name: '交叉解说',
    desc: 'AI解说与原声自然交织，故事完整又有质感，推荐大多数情况',
    type: 'hybrid_narration',
    tags: ['最均衡', '最推荐'],
    icon: <ThunderboltOutlined style={{ color: '#f59e0b' }} />,
    priority: 1,
  },
  {
    id: 'mode-full',
    name: '全片解说',
    desc: '纯AI旁白快速讲完整个故事，节奏紧凑，适合快速传播',
    type: 'full_narration',
    tags: ['最速览', '传播力强'],
    icon: <AudioOutlined style={{ color: '#f472b6' }} />,
    priority: 2,
  },
  {
    id: 'mode-all',
    name: '一键生成三种版本',
    desc: '系统同时输出以上三种不同风格的高质量成片，随意挑选或多平台分发',
    type: 'all_narrations',
    tags: ['最省心', '强烈推荐'],
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
  const [activeClipTaskIds, setActiveClipTaskIds] = useState<string[]>([]);
  
  const [preset, setPreset] = useState(() => localStorage.getItem('dramaclip-export-preset') || '1080p');
  const selectedPreset = PRESETS.find(p => p.value === preset) || PRESETS[0];

  useEffect(() => {
    localStorage.setItem('dramaclip-export-preset', preset);
  }, [preset]);

  // 获取当前活跃的所有自动剪辑任务（支持一键三连多队列展示，并自适应后端 ID 动态重写）
  const activeClipTasks = useTaskQueueStore(s => {
    if (activeClipTaskIds.length === 0) return [];
    
    // 优先匹配缓存的 Task ID
    const matched = s.tasks.filter(t => activeClipTaskIds.includes(t.id));
    if (matched.length > 0) return matched;

    // 若本地生成的临时 ID 被后端真实 Task ID 重写，则通过项目ID及类型定位最新的剪辑任务
    return s.tasks.filter(t => t.type === 'clip' && t.projectId === currentProject?.id);
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

  // 监听并追踪自动剪辑队列进度，只有当全部排队任务完成时，才自动跳转到 Step 4
  useEffect(() => {
    if (activeClipTasks.length === 0) return;
    
    const allCompleted = activeClipTasks.every(t => t.status === 'completed');
    const anyFailed = activeClipTasks.some(t => t.status === 'failed');
    
    if (allCompleted) {
      setApplying(false);
      setActiveClipTaskIds([]);
      message.success('🎉 所有 AI 智能剪辑方案已自动合成完成！进入导出发布阶段。AI 已按最高质量标准完成选片、排序与文案打磨。');
      onNext?.();
    } else if (anyFailed) {
      const failedTask = activeClipTasks.find(t => t.status === 'failed');
      setApplying(false);
      setActiveClipTaskIds([]);
      message.error(`❌ AI 智能剪辑失败: ${failedTask?.error || '合成超时，请重新应用方案！'}`);
    }
  }, [activeClipTasks, onNext]);

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
      const enqueuedIds: string[] = [];
      if (plan.type === 'all_narrations') {
        const id1 = useTaskQueueStore.getState().enqueue('clip', currentProject.id, {
          project_id: currentProject.id,
          scheme: 'original_narration',
          params: {
            segments: aggregatedHighlights,
            clip_mode: 'highlight',
            target_duration: targetDuration,
          },
        });
        const id2 = useTaskQueueStore.getState().enqueue('clip', currentProject.id, {
          project_id: currentProject.id,
          scheme: 'hybrid_narration',
          params: {
            segments: aggregatedHighlights,
            clip_mode: 'highlight',
            target_duration: targetDuration,
          },
        });
        const id3 = useTaskQueueStore.getState().enqueue('clip', currentProject.id, {
          project_id: currentProject.id,
          scheme: 'full_narration',
          params: {
            segments: aggregatedHighlights,
            clip_mode: 'highlight',
            target_duration: targetDuration,
          },
        });
        enqueuedIds.push(id1, id2, id3);
      } else {
        const id = useTaskQueueStore.getState().enqueue('clip', currentProject.id, {
          project_id: currentProject.id,
          scheme: plan.type,
          params: {
            segments: aggregatedHighlights,
            clip_mode: 'highlight',
            target_duration: targetDuration,
          },
        });
        enqueuedIds.push(id);
      }

      setActiveClipTaskIds(enqueuedIds);
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

      {/* 时长已完全由系统智能控制（成片效果优先，默认不限时长）—— 已移除用户可见配置 */}

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
      {activeClipTasks.length > 0 && activeClipTasks.some(t => t.status === 'running' || t.status === 'queued') && (
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
          styles={{ body: { padding: '32px 24px' } }}
          >
            <div style={{ position: 'relative', display: 'inline-block', marginBottom: 20 }}>
              <Spin indicator={<LoadingOutlined style={{ fontSize: 40, color: CYAN }} spin />} />
              <div style={{
                position: 'absolute', top: '50%', left: '50%',
                transform: 'translate(-50%, -50%)',
                fontSize: 18,
              }}>✨</div>
            </div>
            
            <Title level={4} style={{ color: '#e8edff', margin: '0 0 16px 0', fontWeight: 600 }}>
              AI 智能剪辑任务排队合成中
            </Title>
            
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14, textAlign: 'left', marginBottom: 20 }}>
              {activeClipTasks.map(t => (
                <div key={t.id} style={{
                  padding: '12px 16px', borderRadius: 10,
                  background: t.status === 'running' ? 'rgba(0, 212, 255, 0.04)' : 'rgba(255, 255, 255, 0.015)',
                  border: `1px solid ${t.status === 'running' ? `${CYAN}22` : 'rgba(255, 255, 255, 0.04)'}`,
                  transition: 'all 0.3s ease',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                    <Text strong style={{ color: t.status === 'running' ? '#fff' : '#8892a4', fontSize: 13 }}>
                      {t.params?.scheme === 'original_narration' ? '🎬 原片直剪' :
                       t.params?.scheme === 'hybrid_narration' ? '🎙️ 交叉解说' :
                       t.params?.scheme === 'full_narration' ? '🗣️ 全片解说' :
                       '智能剪辑'}
                    </Text>
                    <span style={{ 
                      fontSize: 11, 
                      color: t.status === 'running' ? CYAN : t.status === 'completed' ? '#10b981' : '#6b7b9d',
                      fontWeight: 600
                    }}>
                      {t.status === 'running' ? `${t.progress}%` :
                       t.status === 'completed' ? '已完成' :
                       t.status === 'failed' ? '失败' : '排队中'}
                    </span>
                  </div>
                  {t.status === 'running' && (
                    <>
                      <Progress
                        percent={t.progress}
                        strokeColor={{ '0%': CYAN, '100%': PURPLE }}
                        trailColor="rgba(255, 255, 255, 0.05)"
                        size="small"
                        showInfo={false}
                        style={{ margin: 0 }}
                      />
                      {t.phase && (
                        <div style={{ color: '#4a5a7a', fontSize: 11, marginTop: 4 }}>
                          {t.phase === 'clipping' ? '正在拼接和渲染高光视频片段...' : 
                           t.phase === 'audio' ? '正在融合背景音乐与人声对白...' :
                           t.message || '正在挑选并合成高光片段...'}
                        </div>
                      )}
                    </>
                  )}
                </div>
              ))}
            </div>
            
            <div style={{ borderTop: '1px solid rgba(255, 255, 255, 0.04)', paddingTop: 12, textAlign: 'left' }}>
              <Text style={{ color: '#4a5a7a', fontSize: 11 }}>
                💡 剪辑任务已加入后台队列，正按序执行。您可以直观查看每个方案的生成进度。
              </Text>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
};

export default RecommendPanel;
