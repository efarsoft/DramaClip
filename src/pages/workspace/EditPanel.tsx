/**
 * 智能剪辑面板 — 项目工作区 Step 4
 * 展示片段列表，支持预览与调整，通过任务队列执行剪辑
 */
import React, { useMemo, useState } from 'react';
import {
  Typography, Button, Card, Space, Tag, Switch, Empty, message, Progress, Tooltip,
} from 'antd';
import {
  ScissorOutlined,
  SoundOutlined,
  FileTextOutlined,
  PlayCircleOutlined,
  CheckCircleFilled,
  ArrowRightOutlined,
  StopOutlined,
  ReloadOutlined,
  MinusCircleOutlined,
  EyeOutlined,
  LoadingOutlined,
} from '@ant-design/icons';
import { useProjectStore } from '../../stores/projectStore';
import { useTaskQueueStore, type Task } from '../../stores/taskQueueStore';
import { VideoPlayerModal, MiniPreview } from '../../components/common/VideoPlayer';
import { TaskStatusTag } from '../../components/common/TaskStatus';
const { Title, Text } = Typography;
const CYAN = '#00d4ff';
const PURPLE = '#7c3aed';



const EMOTION_COLORS: Record<string, string> = {
  neutral: '#6b7b9d', joy: '#10b981', anger: '#ef4444', surprise: '#f59e0b', sad: '#6366f1',
};



export interface Segment {
  id: string;
  start: number;
  end: number;
  label: string;
  desc: string;
  emotion: string;
  duration: number;
  video_path?: string;
  score?: number;
}

export interface AnalysisResults {
  highlights?: Array<{
    id?: string;
    segment_id?: string;
    start_time: number;
    end_time: number;
    score?: number;
    label?: string;
    reason?: string;
    video_path?: string;
    emotion_score?: number;
    audio_score?: number;
    visual_score?: number;
    rhythm_score?: number;
    subtitle_text?: string;
  }>;
}

interface Props {
  onNext: () => void;
}

export interface TaskWithResults extends Task {
  results?: AnalysisResults;
}

const EditPanel: React.FC<Props> = ({ onNext }) => {
  const { currentProject, clipTargetDuration, currentVideos } = useProjectStore();

  const { tasks: allTasks, activeTaskId, enqueue, cancel, retry, remove, clearCompleted } = useTaskQueueStore();

  const [segments, setSegments] = useState<Segment[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [previewSegment, setPreviewSegment] = useState<Segment | null>(null);
  // 取当前项目最近的 analyze 任务
  const analyzeTasks = useMemo(
    () => allTasks.filter((t): t is TaskWithResults => t.type === 'analyze'),
    [allTasks],
  );

  // 取当前项目最近的 clip 任务
  const clipTasks = useMemo(
    () => allTasks.filter(t => t.type === 'clip'),
    [allTasks],
  );
  const activeClip = useMemo(
    () => clipTasks.find(t => t.id === activeTaskId),
    [clipTasks, activeTaskId],
  );
  const latestClipResult = useMemo(
    () => clipTasks
      .filter(t => t.status === 'completed')
      .sort((a, b) => (b.completedAt || 0) - (a.completedAt || 0))[0],
    [clipTasks],
  );

  // 从已完成的分析任务中提取片段数据
  const latestAnalysisResult = useMemo(
    () => analyzeTasks
      .filter(t => t.status === 'completed')
      .sort((a, b) => (b.completedAt || 0) - (a.completedAt || 0))[0],
    [analyzeTasks],
  );

  // 同步 segments 数据（来自分析任务结果中的 highlights）
  React.useEffect(() => {
    if (latestAnalysisResult?.results?.highlights) {
      const segs: Segment[] = latestAnalysisResult.results.highlights.map((h, i) => ({
        id: h.id || h.segment_id || `h-${i}`,
        start: h.start_time,
        end: h.end_time,
        label: h.label || h.subtitle_text || `片段 ${i + 1}`,
        desc: h.reason || h.subtitle_text || '',
        emotion: h.emotion_score && h.emotion_score > 0.7 ? 'intense' : 'neutral',
        duration: h.end_time - h.start_time,
        video_path: h.video_path,
        score: h.score,
      }));
      setSegments(segs);
      setSelectedIds(new Set(segs.map(s => s.id)));
    } else {
      setSegments([]);
      setSelectedIds(new Set());
    }
  }, [latestAnalysisResult]);

  // 有活跃剪辑任务 → 展示进度；没活跃但最近完成过 → 可跳转下一步
  const hasClipCompleted = !!latestClipResult;
  const isClipRunning = !!activeClip;

  const toggleSelect = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // ── 确认剪辑：入队 clip 任务 ──
  const handleStartClip = () => {
    if (!currentProject) return;
    if (selectedIds.size === 0) {
      message.warning('请至少选择一个片段');
      return;
    }
    enqueue('clip', currentProject.id, {
      project_id: currentProject.id,
      scheme: useProjectStore.getState().clipScheme || 'original_narration',
      params: {
        segments: Array.from(selectedIds),
        segment_ids: Array.from(selectedIds),
        clip_mode: 'highlight',
      },
    });
    message.success('剪辑任务已加入队列');
  };

  // ── 查看方案（已完成时跳转） ──
  const handleViewResult = () => {
    if (hasClipCompleted) {
      message.success('剪辑完成，进入导出');
      onNext();
    } else {
      message.info('请先完成剪辑');
    }
  };

  if (!currentProject) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
        <Empty description={<span style={{ color: '#6b7b9d' }}>请先应用剪辑方案</span>} image={Empty.PRESENTED_IMAGE_SIMPLE} />
      </div>
    );
  }

  const totalDuration = segments
    .filter(s => selectedIds.has(s.id))
    .reduce((acc, s) => acc + s.duration, 0);

  return (
    <div style={{ maxWidth: 760, margin: '0 auto', padding: '32px 24px', height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* ─── 标题 ─── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24, flexShrink: 0 }}>
        <div>
          <Title level={3} style={{ color: '#e0e6ed', margin: 0 }}>✂️ 智能剪辑</Title>
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

      {/* ─── 可滚动内容区 ─── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden' }}>
        {/* ─── 片段列表（可滚动） ─── */}
        <div style={{ 
          display: 'flex', flexDirection: 'column', gap: 10, 
          flex: 1, overflowY: 'auto', overflowX: 'hidden',
          paddingRight: 4, marginBottom: 16
        }}>
          {segments.map((seg, idx) => {
            const selected = selectedIds.has(seg.id);
            // 片段对应的视频文件路径：优先用 video_path，否则从 currentVideos 查找
            const videoFilePath = seg.video_path || currentVideos[0]?.path || '';
            return (
              <div
                key={seg.id}
                onClick={() => !isClipRunning && toggleSelect(seg.id)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 16,
                  padding: '16px 20px', borderRadius: 12,
                  background: selected ? `linear-gradient(135deg, ${CYAN}0b, ${PURPLE}0b)` : 'rgba(255,255,255,0.015)',
                  border: selected ? `1px solid ${CYAN}55` : '1px solid rgba(255,255,255,0.03)',
                  backdropFilter: 'blur(10px)',
                  cursor: isClipRunning ? 'not-allowed' : 'pointer',
                  transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
                  opacity: selected ? 1 : 0.5,
                  transform: selected ? 'translateY(-2px)' : 'none',
                  boxShadow: selected ? `0 6px 20px ${CYAN}15` : 'none',
                  flexShrink: 0,
                }}
                onMouseEnter={(e) => {
                  if (!isClipRunning) {
                    e.currentTarget.style.background = selected ? `linear-gradient(135deg, ${CYAN}12, ${PURPLE}12)` : 'rgba(255,255,255,0.03)';
                    e.currentTarget.style.borderColor = selected ? `${CYAN}77` : 'rgba(255,255,255,0.06)';
                    e.currentTarget.style.transform = 'translateY(-2px)';
                    e.currentTarget.style.boxShadow = selected ? `0 8px 24px ${CYAN}22` : '0 4px 12px rgba(0,0,0,0.1)';
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isClipRunning) {
                    e.currentTarget.style.background = selected ? `linear-gradient(135deg, ${CYAN}0b, ${PURPLE}0b)` : 'rgba(255,255,255,0.015)';
                    e.currentTarget.style.borderColor = selected ? `${CYAN}44` : 'rgba(255,255,255,0.03)';
                    e.currentTarget.style.transform = selected ? 'translateY(-2px)' : 'none';
                    e.currentTarget.style.boxShadow = selected ? `0 6px 20px ${CYAN}15` : 'none';
                  }
                }}
              >
                {/* 序号 */}
                <span style={{
                  width: 26, height: 26, borderRadius: 8, display: 'flex',
                  alignItems: 'center', justifyContent: 'center',
                  background: selected ? 'rgba(0, 212, 255, 0.12)' : 'rgba(255,255,255,0.05)',
                  color: selected ? CYAN : '#4a5a7a',
                  fontSize: 12, fontWeight: 600, fontFamily: "'JetBrains Mono', monospace",
                }}>{idx + 1}</span>

                {/* 缩略图预览（叠加 AI 评分角标） */}
                {videoFilePath && (
                  <div
                    onClick={(e) => { e.stopPropagation(); setPreviewSegment(seg); }}
                    style={{ flexShrink: 0, position: 'relative', cursor: 'pointer', borderRadius: 6, overflow: 'hidden' }}
                  >
                    <MiniPreview
                      filePath={videoFilePath}
                      width={96}
                      height={54}
                      startTime={seg.start}
                      endTime={seg.end}
                    />
                    
                    {/* AI 精彩度评分小星标 */}
                    {seg.score !== undefined && (
                      <div style={{
                        position: 'absolute', left: 4, top: 4,
                        background: 'rgba(10, 14, 26, 0.75)',
                        padding: '1px 6px', borderRadius: 4,
                        display: 'flex', alignItems: 'center', gap: 2,
                        border: '1px solid rgba(255,255,255,0.1)',
                        backdropFilter: 'blur(4px)',
                        boxShadow: '0 2px 6px rgba(0,0,0,0.2)'
                      }}>
                        <span style={{ fontSize: 9, filter: 'none' }}>⭐</span>
                        <span style={{
                          fontSize: 9, color: '#f59e0b', fontWeight: 700,
                          fontFamily: "'JetBrains Mono', monospace", lineHeight: '1'
                        }}>
                          {(seg.score * 10).toFixed(1)}
                        </span>
                      </div>
                    )}

                    {/* 播放按钮覆盖层 */}
                    <div style={{
                      position: 'absolute', inset: 0,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      background: 'rgba(0,0,0,0.35)',
                      opacity: 0, transition: 'opacity 0.2s',
                    }}
                      className="mini-preview-overlay"
                      onMouseEnter={(e) => (e.currentTarget.style.opacity = '1')}
                      onMouseLeave={(e) => (e.currentTarget.style.opacity = '0')}
                    >
                      <PlayCircleOutlined style={{ fontSize: 20, color: '#fff' }} />
                    </div>
                  </div>
                )}

                {/* 标签与描述对白 */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, color: selected ? '#fff' : '#e0e6ed', fontSize: 14, marginBottom: 4, letterSpacing: '0.2px' }}>
                    {seg.label}
                  </div>
                  <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    <Text style={{ color: selected ? '#6b7b9d' : '#4a5a7a', fontSize: 12 }}>
                      {seg.desc || 'AI 多维过滤精彩片段'}
                    </Text>
                  </div>
                </div>

                {/* 时长 */}
                <span style={{
                  fontSize: 12, fontFamily: "'JetBrains Mono', monospace', monospace",
                  color: selected ? CYAN : '#6b7b9d', whiteSpace: 'nowrap', fontWeight: 600
                }}>
                  {seg.duration.toFixed(1)}s
                </span>

                {/* 情绪情绪标签 */}
                <div style={{
                  padding: '2px 8px', borderRadius: 6, fontSize: 11, fontWeight: 500,
                  background: `${EMOTION_COLORS[seg.emotion] || '#6b7b9d'}15`,
                  color: EMOTION_COLORS[seg.emotion] || '#6b7b9d',
                  border: `1px solid ${EMOTION_COLORS[seg.emotion] || '#6b7b9d'}22`,
                  flexShrink: 0,
                }}>
                  {seg.emotion.toUpperCase()}
                </div>

                {/* 预览按钮 */}
                {videoFilePath && (
                  <Tooltip title="预览片段">
                    <Button
                      type="text"
                      size="small"
                      icon={<EyeOutlined />}
                      onClick={(e) => { e.stopPropagation(); setPreviewSegment(seg); }}
                      style={{ color: '#4a5a7a', flexShrink: 0 }}
                      onMouseEnter={(e) => (e.currentTarget.style.color = CYAN)}
                      onMouseLeave={(e) => (e.currentTarget.style.color = '#4a5a7a')}
                    />
                  </Tooltip>
                )}

                {/* 选择指示器 */}
                <div style={{
                  width: 18, height: 18, borderRadius: 5,
                  border: `2px solid ${selected ? CYAN : '#2a3050'}`,
                  background: selected ? CYAN : 'transparent',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  transition: 'all 0.2s',
                  flexShrink: 0,
                }}>
                  {selected && <CheckCircleFilled style={{ color: '#0a0e1a', fontSize: 11 }} />}
                </div>
              </div>
            );
          })}
        </div>

        {/* ─── 附加选项 ─── */}
        <Card style={{
          background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.06)',
          borderRadius: 12, marginBottom: 16, flexShrink: 0,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <Space>
              <SoundOutlined style={{ color: CYAN }} />
              <Text style={{ color: '#c8d0dc' }}>AI 旁白解说</Text>
            </Space>
            <Switch defaultChecked size="small" style={{ background: '#2a3050' }} disabled={isClipRunning} />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <Space>
              <FileTextOutlined style={{ color: PURPLE }} />
              <Text style={{ color: '#c8d0dc' }}>自动字幕</Text>
            </Space>
            <Switch defaultChecked size="small" style={{ background: '#2a3050' }} disabled={isClipRunning} />
          </div>
        </Card>

        {/* ─── 剪辑进度（运行中） ─── */}
        {isClipRunning && activeClip && (
          <Card style={{
            marginBottom: 16, flexShrink: 0,
            background: 'rgba(0,212,255,0.03)',
            borderColor: `${CYAN}22`, borderRadius: 12,
          }}>
            <div style={{ textAlign: 'center', marginBottom: 12 }}>
              <LoadingOutlined style={{ fontSize: 28, color: CYAN }} />
              <Title level={4} style={{ color: '#e0e6ed', margin: '8px 0 0', fontSize: 16 }}>正在剪辑...</Title>
              <Text style={{ color: '#4a5a7a', fontSize: 13 }}>{activeClip.phase}</Text>
            </div>
            <Progress
              percent={activeClip.progress}
              strokeColor={{ '0%': CYAN, '100%': PURPLE }}
              trailColor="rgba(255,255,255,0.05)"
            />
            <div style={{ marginTop: 8, textAlign: 'center' }}>
              <Text style={{ color: '#4a5a7a', fontSize: 13 }}>{activeClip.progress}%</Text>
            </div>
          </Card>
        )}

        {/* ─── 剪辑队列表 ─── */}
        {clipTasks.length > 0 && (
          <Card
            style={{
              marginBottom: 16, background: 'rgba(255,255,255,0.02)',
              borderColor: 'rgba(255,255,255,0.06)', borderRadius: 12,
              flexShrink: 0,
            }}
            title={
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ color: '#e0e6ed' }}>📋 剪辑队列</span>
                <Button size="small" type="text" onClick={clearCompleted}
                  style={{ color: '#4a5a7a', fontSize: 12 }}>
                  清理已完成
                </Button>
              </div>
            }
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {clipTasks.map(task => (
                <div key={task.id} style={{
                  display: 'flex', alignItems: 'center', gap: 12,
                  padding: '8px 12px', borderRadius: 8,
                  background: task.id === activeTaskId ? 'rgba(0,212,255,0.04)' : 'transparent',
                  border: `1px solid ${task.id === activeTaskId ? `${CYAN}22` : 'transparent'}`,
                }}>
                  <TaskStatusTag status={task.status} taskType="clip" />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <Text style={{ color: '#e0e6ed', fontSize: 13 }}>智能剪辑</Text>
                    {task.status === 'running' && (
                      <Progress percent={task.progress} strokeColor={{ '0%': CYAN, '100%': PURPLE }}
                        trailColor="rgba(255,255,255,0.05)" size="small" style={{ margin: 0 }} />
                    )}
                    {task.status === 'failed' && task.error && (
                      <Text style={{ color: '#ef4444', fontSize: 11 }}>{task.error}</Text>
                    )}
                    {task.status === 'queued' && (
                      <Text style={{ color: '#4a5a7a', fontSize: 11 }}>等待中</Text>
                    )}
                  </div>
                  <div style={{ flexShrink: 0, display: 'flex', gap: 4 }}>
                    {task.status === 'running' && (
                      <Tooltip title="取消">
                        <Button size="small" shape="circle" icon={<StopOutlined />}
                          onClick={() => cancel(task.id)} style={{ border: 'none', color: '#f59e0b' }} />
                      </Tooltip>
                    )}
                    {task.status === 'failed' && (
                      <Tooltip title="重试">
                        <Button size="small" shape="circle" icon={<ReloadOutlined />}
                          onClick={() => retry(task.id)} style={{ border: 'none', color: CYAN }} />
                      </Tooltip>
                    )}
                    {(task.status === 'completed' || task.status === 'cancelled') && (
                      <Tooltip title="移除">
                        <Button size="small" shape="circle" icon={<MinusCircleOutlined />}
                          onClick={() => remove(task.id)} style={{ border: 'none', color: '#4a5a7a' }} />
                      </Tooltip>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        )}

        {/* ─── 动作按钮区（固定） ─── */}
        <div style={{ display: 'flex', justifyContent: 'center', gap: 12, flexWrap: 'wrap', flexShrink: 0 }}>
          {!isClipRunning && !hasClipCompleted && (
            <Button
              type="primary"
              size="large"
              onClick={handleStartClip}
              disabled={selectedIds.size === 0}
              icon={<ScissorOutlined />}
              style={{
                height: 48, borderRadius: 10, padding: '0 40px',
                background: `linear-gradient(135deg, ${CYAN}, ${PURPLE})`,
                border: 'none', fontWeight: 600, fontSize: 15, letterSpacing: 1,
                boxShadow: `0 0 24px ${CYAN}33`,
              }}
            >
              确认剪辑
            </Button>
          )}
          {!isClipRunning && hasClipCompleted && (
            <>
              <Button
                type="primary"
                size="large"
                onClick={handleViewResult}
                icon={<ArrowRightOutlined />}
                style={{
                  height: 48, borderRadius: 10, padding: '0 40px',
                  background: '#10b981', border: 'none', fontWeight: 600, fontSize: 15,
                }}
              >
                查看剪辑结果
              </Button>
              <Button
                size="large"
                onClick={handleStartClip}
                icon={<ScissorOutlined />}
                style={{
                  height: 48, borderRadius: 10, padding: '0 24px',
                  borderColor: `${CYAN}44`, color: CYAN,
                }}
              >
                重新剪辑
              </Button>
            </>
          )}
        </div>
      </div>

      {/* ─── 片段视频预览模态框 ─── */}
      <VideoPlayerModal
        open={!!previewSegment}
        onClose={() => setPreviewSegment(null)}
        filePath={previewSegment?.video_path || currentVideos[0]?.path || ''}
        title={previewSegment?.label}
        startTime={previewSegment?.start}
        endTime={previewSegment?.end}
      />
    </div>
  );
};

export default EditPanel;
