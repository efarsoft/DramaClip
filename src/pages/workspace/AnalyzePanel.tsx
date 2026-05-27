/**
 * AI 分析面板 — 项目工作区 Step 2
 * 集成任务队列，支持排队、重试、取消
 * 精细化步骤条、本地离线模型加载指示器与气泡式对白剧本流美化
 */
import React, { useMemo } from 'react';
import {
  Typography,
  Button,
  Progress,
  Card,
  Alert,
  Spin,
  Space,
  Empty,
  Tooltip,
  Tag,
  message,
  Row,
  Col,
} from 'antd';
import {
  PlayCircleOutlined,
  StopOutlined,
  CheckCircleFilled,
  ReloadOutlined,
  MinusCircleOutlined,
  LoadingOutlined,
  CopyOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';
import { useProjectStore } from '../../stores/projectStore';
import { useTaskQueueStore, type Task } from '../../stores/taskQueueStore';
import { EmotionCurve } from '../../components/chart/EmotionCurve';
import { TaskStatusTag } from '../../components/common/TaskStatus';
import { analyzeApi } from '../../services/ipc';

const { Title, Text } = Typography;
const CYAN = '#00d4ff';
const PURPLE = '#7c3aed';

// ─── 类型定义 ───

interface ASRSegment {
  id: string;
  text: string;
  start: number;
  end: number;
  speaker: string;
}

interface EmotionPoint {
  timestamp: number;
  emotion: string;
  intensity: number;
}

interface AnalysisResults {
  asr?: { segments: ASRSegment[]; duration?: number };
  emotion?: { emotion_curve: EmotionPoint[] };
  highlights?: unknown[];
}

const PHASE_LABELS: Record<string, string> = {
  preparing: '音频准备',
  asr: '语音识别',
  diarization: '说话人分离',
  merge: '整合字幕',
  emotion: '情绪分析',
  visual: '视觉分析',
  rhythm: '节奏分析',
  highlight: '高光识别',
  saving: '保存结果',
  completed: '分析完成',
  failed: '分析失败',
  idle: '准备就绪',
};

// 9 阶段的 AI 分析管道
const ANALYZE_STEPS = [
  { phase: 'preparing', label: '准备音频', icon: '🎧' },
  { phase: 'asr', label: '语音识别', icon: '🗣️' },
  { phase: 'diarization', label: '角色分离', icon: '👥' },
  { phase: 'merge', label: '整合字幕', icon: '📎' },
  { phase: 'emotion', label: '情绪分析', icon: '🎭' },
  { phase: 'visual', label: '画面分析', icon: '👁️' },
  { phase: 'rhythm', label: '节奏分析', icon: '🎵' },
  { phase: 'highlight', label: '高光识别', icon: '✨' },
  { phase: 'saving', label: '归档保存', icon: '💾' },
];

// ── 单条分析任务行 ──

const AnalyzeTaskRow: React.FC<{
  task: Task;
  onCancel: (id: string) => void;
  onRetry: (id: string) => void;
  onRemove: (id: string) => void;
}> = ({ task, onCancel, onRetry, onRemove }) => {
  const { activeTaskId } = useTaskQueueStore();
  const { currentVideos } = useProjectStore();
  const isActive = task.id === activeTaskId;

  // 解析当前任务对应的视频名称
  const displayName = useMemo(() => {
    const episodeIds = task.params?.episode_ids as string[] | undefined;
    if (!episodeIds || episodeIds.length === 0) return 'AI 智能分析任务';
    const matched = currentVideos.find(v => v.id === episodeIds[0]);
    if (!matched) return 'AI 智能分析任务';
    if (episodeIds.length > 1) {
      return `${matched.name} 等 ${episodeIds.length} 个视频`;
    }
    return matched.name;
  }, [task.params, currentVideos]);

  return (
    <div
      style={{
        display: 'flex', alignItems: 'center', gap: 12,
        padding: '10px 14px', borderRadius: 8,
        background: isActive ? 'rgba(0,212,255,0.03)' : 'rgba(255,255,255,0.01)',
        border: `1px solid ${isActive ? `${CYAN}22` : 'rgba(255,255,255,0.04)'}`,
        transition: 'all 0.2s',
      }}
    >
      <div style={{ flexShrink: 0, width: 72 }}>
        <TaskStatusTag status={task.status} taskType="analyze" />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <Text style={{ color: '#e0e6ed', fontSize: 13, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {displayName}
          </Text>
          <Text style={{ color: '#4a5a7a', fontSize: 11 }}>
            {task.phase ? (PHASE_LABELS[task.phase] || task.phase) : ''}
          </Text>
        </div>
        {task.status === 'running' && (
          <Progress
            percent={task.progress}
            strokeColor={{ '0%': CYAN, '100%': PURPLE }}
            trailColor="rgba(255,255,255,0.05)"
            size="small"
            style={{ margin: 0 }}
          />
        )}
        {task.status === 'failed' && task.error && (
          <Text style={{ color: '#ef4444', fontSize: 11, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{task.error}</Text>
        )}
        {task.status === 'queued' && (
          <Text style={{ color: '#4a5a7a', fontSize: 11 }}>
            {new Date(task.createdAt).toLocaleTimeString('zh-CN')} 加入队列
          </Text>
        )}
      </div>
      <div style={{ flexShrink: 0, display: 'flex', gap: 4 }}>
        {task.status === 'running' && (
          <Tooltip title="取消">
            <Button size="small" shape="circle" icon={<StopOutlined />} onClick={() => onCancel(task.id)}
              style={{ border: 'none', color: '#f59e0b', background: 'transparent' }} />
          </Tooltip>
        )}
        {task.status === 'failed' && (
          <Tooltip title="重试">
            <Button size="small" shape="circle" icon={<ReloadOutlined />} onClick={() => onRetry(task.id)}
              style={{ border: 'none', color: CYAN, background: 'transparent' }} />
          </Tooltip>
        )}
        {(task.status === 'completed' || task.status === 'cancelled') && (
          <Tooltip title="移除">
            <Button size="small" shape="circle" icon={<MinusCircleOutlined />} onClick={() => onRemove(task.id)}
              style={{ border: 'none', color: '#4a5a7a', background: 'transparent' }} />
          </Tooltip>
        )}
      </div>
    </div>
  );
};

// ── 主面板 ──

interface Props {
  onNext: () => void;
}

const AnalyzePanel: React.FC<Props> = ({ onNext }) => {
  const { currentProject, selectedEpisodeIds, currentVideos } = useProjectStore();
  const { tasks: allTasks, activeTaskId, cancel, retry, remove, clearCompleted, isRunning } = useTaskQueueStore();

  const videoIdsKey = useMemo(() => currentVideos.map(v => v.id).join(','), [currentVideos]);

  // ─── 自动同步已完成的磁盘缓存分析结果到 Zustand Store 中 ───
  React.useEffect(() => {
    if (!currentProject || currentVideos.length === 0) return;

    const syncCompletedTasks = async () => {
      try {
        const videoIds = currentVideos.map(v => v.id);
        const { results } = await analyzeApi.getCompletedResults(currentProject.id, videoIds);

        if (results && Object.keys(results).length > 0) {
          let hasInjected = false;
          const nextTasks = [...useTaskQueueStore.getState().tasks];

          Object.keys(results).forEach(vid => {
            // 检查当前 store 中是否已存在对该 vid 的 analyze 任务
            const hasTask = nextTasks.some(t => {
              const ids = t.params?.episode_ids as string[] | undefined;
              return t.type === 'analyze' && ids && ids.includes(vid);
            });

            if (!hasTask) {
              const val = results[vid];
              const mockTaskId = `analyze-${currentProject.id}-${vid}`;
              
              nextTasks.push({
                id: mockTaskId,
                type: 'analyze',
                projectId: currentProject.id,
                status: 'completed',
                progress: 100,
                phase: 'completed',
                message: '分析完成 (已加载历史缓存)',
                params: {
                  project_id: currentProject.id,
                  episode_id: vid,
                  episode_ids: [vid],
                },
                results: {
                  asr: val.asr,
                  emotion: val.emotion,
                  highlights: val.highlights,
                },
                createdAt: Date.now(),
                completedAt: Date.now(),
              });
              hasInjected = true;
            }
          });

          if (hasInjected) {
            useTaskQueueStore.setState({ tasks: nextTasks });
          }
        }
      } catch (err) {
        console.error('[AnalyzePanel] 自动同步已完成任务缓存失败:', err);
      }
    };

    syncCompletedTasks();
  }, [currentProject?.id, videoIdsKey]);

  // 只取当前项目的 analyze 类型任务
  const analyzeTasks = useMemo(
    () => allTasks.filter(t => t.type === 'analyze' && t.projectId === currentProject?.id),
    [allTasks, currentProject?.id],
  );
  const activeAnalyze = useMemo(
    () => analyzeTasks.find(t => t.id === activeTaskId),
    [analyzeTasks, activeTaskId],
  );
  const latestCompleted = useMemo(
    () => analyzeTasks
      .filter(t => t.status === 'completed')
      .sort((a, b) => (b.completedAt || 0) - (a.completedAt || 0))[0],
    [analyzeTasks],
  );

  // ─── 聚合所选视频的分析数据（虚拟连续时间轴叠拼） ───
  const { mergedAsrSegments, mergedEmotionCurve } = useMemo(() => {
    let currentOffset = 0;
    const mergedAsr: ASRSegment[] = [];
    const mergedEmotion: EmotionPoint[] = [];

    // 按照用户勾选所选视频的顺序（selectedEpisodeIds）依次堆叠
    for (const episodeId of selectedEpisodeIds) {
      // 如果该视频当前有正在运行或排队中的任务，说明之前的分析已失效，我们需要等待新分析完成，因此忽略旧的完成任务并清空显示
      const hasActiveTask = analyzeTasks.some(t => {
        const ids = t.params?.episode_ids as string[] | undefined;
        return (t.status === 'running' || t.status === 'queued') && ids && ids.includes(episodeId);
      });

      if (hasActiveTask) {
        // 忽略旧的完成结果，等待新分析
        const videoMeta = currentVideos.find(v => v.id === episodeId);
        if (videoMeta && videoMeta.duration) {
          currentOffset += videoMeta.duration;
        }
        continue;
      }

      // 找到该视频对应的已完成分析任务
      const matchedTask = analyzeTasks.find(t => {
        const ids = t.params?.episode_ids as string[] | undefined;
        return t.status === 'completed' && ids && ids.includes(episodeId);
      });

      if (!matchedTask) {
        // 如果该视频任务未完成，累加它的元数据时长
        const videoMeta = currentVideos.find(v => v.id === episodeId);
        if (videoMeta && videoMeta.duration) {
          currentOffset += videoMeta.duration;
        }
        continue;
      }

      const results = matchedTask.results as AnalysisResults | undefined;
      const asr = results?.asr;
      const emotion = results?.emotion;

      // 1. 堆叠 ASR 对白字幕
      if (asr && asr.segments) {
        asr.segments.forEach(seg => {
          mergedAsr.push({
            ...seg,
            id: `${matchedTask.id}-${seg.id}`,
            start: seg.start + currentOffset,
            end: seg.end + currentOffset,
          });
        });
      }

      // 2. 堆叠情绪数据点
      if (emotion && emotion.emotion_curve) {
        emotion.emotion_curve.forEach(pt => {
          mergedEmotion.push({
            ...pt,
            timestamp: pt.timestamp + currentOffset,
          });
        });
      }

      // 3. 累加当前视频时长
      const videoMeta = currentVideos.find(v => v.id === episodeId);
      const duration = asr?.duration ?? videoMeta?.duration ?? (asr?.segments && asr.segments.length > 0 ? asr.segments[asr.segments.length - 1].end : 0);
      currentOffset += duration;
    }

    return { mergedAsrSegments: mergedAsr, mergedEmotionCurve: mergedEmotion };
  }, [selectedEpisodeIds, analyzeTasks, currentVideos]);

  const asrSegments = mergedAsrSegments;
  const emotionCurve = mergedEmotionCurve;

  // 是否有分析结果可展示
  const hasResults = latestCompleted || analyzeTasks.some(t => t.status === 'completed');

  // 获取当前选中的视频列表
  const selectedVideos = useMemo(() => {
    return currentVideos.filter(v => selectedEpisodeIds.includes(v.id));
  }, [currentVideos, selectedEpisodeIds]);

  // 当前任务的 phase 索引
  const currentStepIndex = useMemo(() => {
    if (!activeAnalyze) return -1;
    return ANALYZE_STEPS.findIndex(s => s.phase === activeAnalyze.phase);
  }, [activeAnalyze]);

  // 解析当前活动任务的视频名称
  const activeEpisodeName = useMemo(() => {
    if (!activeAnalyze) return null;
    const episodeIds = activeAnalyze.params?.episode_ids as string[] | undefined;
    if (!episodeIds || episodeIds.length === 0) return null;
    const matched = currentVideos.find(v => v.id === episodeIds[0]);
    if (!matched) return null;
    if (episodeIds.length > 1) {
      return `${matched.name} 等 ${episodeIds.length} 个视频`;
    }
    return matched.name;
  }, [activeAnalyze, currentVideos]);

  // 判断并获取当前任务所属的离线模型加载信息
  const modelInfo = useMemo(() => {
    if (!activeAnalyze) return null;
    const msg = activeAnalyze.message.toLowerCase();
    const phase = activeAnalyze.phase;
    
    const isModel = msg.includes('模型') || msg.includes('model') || msg.includes('加载') || msg.includes('loading') || msg.includes('download') || msg.includes('下载') || msg.includes('init') || msg.includes('初始化');
    if (!isModel) return null;

    let modelName = 'AI 离线推理模型';
    let modelDesc = '提示：模型文件完全运行于本地 CPU/GPU，不消耗您的云端额度及外网流量。首次启动时载入内存需要较多时间。';
    let icon = '📦';

    if (phase === 'asr') {
      modelName = 'Whisper-tiny 离线声学模型';
      modelDesc = '正在从本地磁盘载入多国语/中文声学预训练模型至内存。首次加载将由 CPU/GPU 预热缓存，后续分析将极大提速。';
      icon = '🗣️';
    } else if (phase === 'diarization') {
      modelName = 'PyAnnote 说话人分离与追踪模型';
      modelDesc = '正在加载离线声纹提取与聚类模型，用于精准计算不同角色说话的时间区间与声轨重叠比例。';
      icon = '👥';
    } else if (phase === 'emotion') {
      modelName = 'Voice Emotion 声学情绪多维分类模型';
      modelDesc = '正在加载情绪分类模型。分析人声的音高、响度、语调抖动及共振峰分布，为剧情反转及高潮发掘提供特征依据。';
      icon = '🎭';
    } else if (phase === 'visual') {
      modelName = 'MobileNetV3 视觉画面特征提取模型';
      modelDesc = '正在载入视觉分类与关键帧检测权重。计算视频帧的构图明暗、景别过渡、镜头移动速度与场景切换频率。';
      icon = '👁️';
    } else if (phase === 'rhythm') {
      modelName = 'Librosa 离线音轨节奏与节拍分析引擎';
      modelDesc = '正在载入波形分析算法，计算背景音乐节拍点（BPM）、声能密度包络、以及人声音频包络的强弱对比。';
      icon = '🎵';
    } else if (phase === 'highlight') {
      modelName = '多维特征多模态融合高光融合打分算法模型';
      modelDesc = '正在加载高光打分模型。汇聚对白、声能、画面、情绪等多维时序信号进行融合分析，生成片段推荐度评分。';
      icon = '✨';
    }

    return { modelName, modelDesc, icon };
  }, [activeAnalyze]);

  // ── 启动分析 ──
  const handleStart = async () => {
    if (!currentProject) return;
    const ids = selectedEpisodeIds.length > 0 ? selectedEpisodeIds : [];
    if (ids.length === 0) {
      message.warning('请先在导入页面选择要分析的视频');
      return;
    }

    // 重新分析时，取消任何当前正在运行的分析任务以释放 GPU/CPU 后端子进程资源，然后彻底原子性清除旧分析任务，确保界面数据即时清空
    const { tasks: oldTasks, cancel: cancelTask } = useTaskQueueStore.getState();
    const activeTasks = oldTasks.filter(t => t.type === 'analyze' && t.projectId === currentProject.id && (t.status === 'running' || t.status === 'queued'));
    for (const t of activeTasks) {
      try {
        await cancelTask(t.id);
      } catch (err) {
        console.error('Failed to cancel active task:', err);
      }
    }

    // 原子性地从 Store 中一次性移除本项目的全部分析任务，确保界面彻底清空、从零开始
    useTaskQueueStore.setState(s => ({
      tasks: s.tasks.filter(t => !(t.type === 'analyze' && t.projectId === currentProject.id))
    }));
    
    const { ipcClient } = await import('../../services/ipc');
    try {
      const result = await ipcClient.call<{ task_ids: string[] }>('analyze.start', {
        project_id: currentProject.id,
        episode_ids: ids,
      });
      
      if (result?.task_ids && result.task_ids.length > 0) {
        const { addRunningTask } = useTaskQueueStore.getState();
        result.task_ids.forEach((taskId: string, index: number) => {
          addRunningTask('analyze', currentProject.id, taskId, {
            project_id: currentProject.id,
            episode_id: ids[index],
            episode_ids: [ids[index]],
          });
        });
        message.success(`已成功启动 ${result.task_ids.length} 个分析任务`);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      message.error(`启动分析失败: ${msg}`);
    }
  };

  const handleCopyText = (text: string) => {
    navigator.clipboard.writeText(text);
    message.success({
      content: '台词内容已复制',
      duration: 1.5,
    });
  };

  const handleCopyTimestamp = (start: number, end: number) => {
    const timeStr = `${start.toFixed(2)}s ~ ${end.toFixed(2)}s`;
    navigator.clipboard.writeText(timeStr);
    message.success({
      content: `已复制时间轴: ${timeStr}`,
      duration: 1.5,
    });
  };

  if (!currentProject) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
        <Empty description={<span style={{ color: '#6b7b9d' }}>请先导入视频</span>} image={Empty.PRESENTED_IMAGE_SIMPLE} />
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto', padding: '24px 32px' }}>
      {/* 注入呼吸灯动效与滚动条美化 CSS */}
      <style>{`
        @keyframes pulse-glow {
          0% { transform: scale(0.97); opacity: 0.8; box-shadow: 0 0 0 0 rgba(0, 212, 255, 0.4); }
          70% { transform: scale(1); opacity: 1; box-shadow: 0 0 0 10px rgba(0, 212, 255, 0); }
          100% { transform: scale(0.97); opacity: 0.8; box-shadow: 0 0 0 0 rgba(0, 212, 255, 0); }
        }
        @keyframes pulse-icon {
          0% { transform: scale(1); filter: drop-shadow(0 0 2px rgba(0, 212, 255, 0.4)); }
          50% { transform: scale(1.22); filter: drop-shadow(0 0 8px rgba(0, 212, 255, 0.9)); }
          100% { transform: scale(1); filter: drop-shadow(0 0 2px rgba(0, 212, 255, 0.4)); }
        }
        .step-pulse {
          animation: pulse-glow 2.5s infinite ease-in-out;
        }
        .icon-active {
          animation: pulse-icon 1.5s infinite ease-in-out;
          display: inline-block;
        }
        .subtitles-scroll::-webkit-scrollbar {
          width: 5px;
        }
        .subtitles-scroll::-webkit-scrollbar-track {
          background: rgba(255, 255, 255, 0.01);
          border-radius: 4px;
        }
        .subtitles-scroll::-webkit-scrollbar-thumb {
          background: rgba(255, 255, 255, 0.08);
          border-radius: 4px;
        }
        .subtitles-scroll::-webkit-scrollbar-thumb:hover {
          background: rgba(255, 255, 255, 0.15);
        }
        .dialogue-segment-card {
          position: relative;
        }
        .dialogue-segment-card:hover {
          background: rgba(255, 255, 255, 0.04) !important;
          border-color: rgba(255, 255, 255, 0.08) !important;
          box-shadow: 0 6px 16px rgba(0, 0, 0, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.05);
          transform: translateY(-1.5px);
        }
        .dialogue-actions {
          opacity: 0;
          transform: translateX(10px);
          transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .dialogue-segment-card:hover .dialogue-actions {
          opacity: 1;
          transform: translateX(0);
        }
        .dialogue-action-btn {
          color: #4a5a7a !important;
          background: transparent !important;
          border: none !important;
          transition: all 0.2s !important;
        }
        .dialogue-action-btn:hover {
          color: #00d4ff !important;
          background: rgba(255, 255, 255, 0.05) !important;
          transform: scale(1.1);
        }
      `}</style>

      {/* ─── 标题区 ─── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <Title level={3} style={{ color: '#e0e6ed', margin: 0, fontWeight: 700 }}>🤖 AI 智能分析</Title>
          <Text style={{ color: '#4a5a7a', fontSize: 13 }}>
            {currentProject.name} · 多维引擎协作，自动提取对白、情绪及高光方案
          </Text>
        </div>
        <Space>
          {!activeAnalyze ? (
            <Button
              type="primary"
              icon={hasResults ? <ReloadOutlined /> : <PlayCircleOutlined />}
              onClick={handleStart}
              disabled={isRunning}
              style={{
                borderRadius: 8, height: 40, padding: '0 24px',
                background: `linear-gradient(135deg, ${CYAN}, ${PURPLE})`,
                border: 'none', fontWeight: 600,
                boxShadow: `0 4px 15px ${CYAN}33`,
              }}
            >
              {isRunning ? '队列处理中...' : (hasResults ? '重新分析' : '开始分析')}
            </Button>
          ) : null}
          {hasResults && !activeAnalyze && (
            <Button
              type="primary"
              onClick={onNext}
              icon={<CheckCircleFilled />}
              style={{
                borderRadius: 8, height: 40, padding: '0 24px',
                background: '#10b981', border: 'none', fontWeight: 600,
                boxShadow: '0 4px 15px rgba(16, 185, 129, 0.25)',
              }}
            >
              查看方案
            </Button>
          )}
        </Space>
      </div>

      <Row gutter={[24, 24]}>
        {/* 左列：当前素材、进度、情绪曲线、队列 */}
        <Col xs={24} lg={12}>
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            
            {/* 当前选中待分析素材展示 */}
            <div style={{
              padding: '14px 18px',
              borderRadius: 12,
              background: 'rgba(255, 255, 255, 0.01)',
              border: '1px solid rgba(255, 255, 255, 0.03)',
              boxShadow: '0 4px 12px rgba(0, 0, 0, 0.1)',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                <Text style={{ color: '#94a3b8', fontSize: 12, fontWeight: 600 }}>
                  🎬 当前选中的素材范围 ({selectedVideos.length} 个视频)
                </Text>
                <Text style={{ color: '#4a5a7a', fontSize: 11 }}>
                  若需调整，可返回【第一步：导入】勾选
                </Text>
              </div>
              {selectedVideos.length > 0 ? (
                <div style={{
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: 6,
                  maxHeight: 90,
                  overflowY: 'auto',
                  paddingRight: 4
                }} className="subtitles-scroll">
                  {selectedVideos.map(v => (
                    <Tag
                      key={v.id}
                      style={{
                        background: 'rgba(0, 212, 255, 0.04)',
                        border: '1px solid rgba(0, 212, 255, 0.12)',
                        color: CYAN,
                        borderRadius: 6,
                        padding: '3px 10px',
                        fontSize: 12,
                        margin: 0,
                        display: 'flex',
                        alignItems: 'center',
                        gap: 4,
                        fontWeight: 500,
                        boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.02)',
                      }}
                    >
                      <span>🎥</span>
                      <span style={{ maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {v.name}
                      </span>
                    </Tag>
                  ))}
                </div>
              ) : (
                <div style={{
                  padding: '10px 14px',
                  borderRadius: 8,
                  background: 'rgba(239, 68, 68, 0.03)',
                  border: '1px dashed rgba(239, 68, 68, 0.18)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                }}>
                  <span style={{ fontSize: 14 }}>⚠️</span>
                  <Text style={{ color: '#ef4444', fontSize: 12, fontWeight: 500 }}>
                    未选择任何视频，请先返回【第一步：导入】选择需要分析的视频素材！
                  </Text>
                </div>
              )}
            </div>

            {/* 精细化分析流水线进度 */}
            {activeAnalyze && (
              <Card style={{
                background: 'rgba(0, 212, 255, 0.02)',
                borderColor: `${CYAN}22`,
                borderRadius: 12,
                boxShadow: '0 4px 20px rgba(0, 0, 0, 0.15)'
              }}>
                {/* 主状态进度条 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 12 }}>
                  <Spin indicator={<LoadingOutlined style={{ fontSize: 16, color: CYAN }} spin />} />
                  <div style={{ flex: 1 }}>
                    <Text strong style={{ color: '#e0e6ed', fontSize: 14 }}>
                      {activeEpisodeName ? `【${activeEpisodeName}】` : ''}
                      {PHASE_LABELS[activeAnalyze.phase] || activeAnalyze.phase || '分析中'}
                    </Text>
                    {activeAnalyze.message && (
                      <Text style={{ color: '#6b7b9d', fontSize: 12, display: 'block', marginTop: 2 }}>
                        {activeAnalyze.message}
                      </Text>
                    )}
                  </div>
                  <Text style={{ color: CYAN, fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, fontSize: 16 }}>
                    {activeAnalyze.progress}%
                  </Text>
                </div>
                
                <Progress
                  percent={activeAnalyze.progress}
                  strokeColor={{ '0%': CYAN, '100%': PURPLE }}
                  trailColor="rgba(255,255,255,0.04)"
                  style={{ marginBottom: 20 }}
                />

                {/* AI 引擎串联流水线 */}
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(5, 1fr)',
                  gap: '8px 4px',
                  padding: '12px 8px',
                  background: 'rgba(255, 255, 255, 0.01)',
                  borderRadius: 8,
                  border: '1px solid rgba(255, 255, 255, 0.03)'
                }}>
                  {ANALYZE_STEPS.map((s, idx) => {
                    const isCurrent = idx === currentStepIndex;
                    const isFinished = idx < currentStepIndex;
                    
                    let color = '#4a5a7a';
                    let bg = 'transparent';
                    let border = '1px solid transparent';
                    
                    if (isCurrent) {
                      color = CYAN;
                      bg = 'rgba(0, 212, 255, 0.08)';
                      border = `1px solid ${CYAN}33`;
                    } else if (isFinished) {
                      color = '#10b981';
                      bg = 'rgba(16, 185, 129, 0.04)';
                    }

                    return (
                      <div
                        key={s.phase}
                        className={isCurrent ? 'step-pulse' : ''}
                        style={{
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'center',
                          justifyContent: 'center',
                          padding: '8px 4px',
                          borderRadius: 6,
                          background: bg,
                          border: border,
                          transition: 'all 0.3s',
                          position: 'relative',
                        }}
                      >
                        <span
                          className={isCurrent ? 'icon-active' : ''}
                          style={{ fontSize: 16, marginBottom: 2, filter: isFinished || isCurrent ? 'none' : 'grayscale(100%) opacity(40%)' }}
                        >
                          {s.icon}
                        </span>
                        <span style={{ fontSize: 10, color: color, fontWeight: isCurrent || isFinished ? 600 : 400 }}>
                          {s.label}
                        </span>
                        
                        {/* 完成状态小角标 */}
                        {isFinished && (
                          <div style={{
                            position: 'absolute', right: 4, top: 4,
                            width: 6, height: 6, borderRadius: '50%',
                            background: '#10b981'
                          }} />
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* 本地模型加载专项提示卡片 */}
                {modelInfo && (
                  <div style={{
                    marginTop: 14,
                    padding: '14px 16px',
                    borderRadius: 8,
                    background: 'rgba(124, 58, 237, 0.03)',
                    border: `1px dashed ${PURPLE}44`,
                    display: 'flex',
                    alignItems: 'start',
                    gap: 12,
                    animation: 'pulse-glow 3s infinite ease-in-out',
                  }}>
                    <span style={{ fontSize: 20, marginTop: 2 }}>{modelInfo.icon}</span>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Text style={{ color: '#a855f7', fontSize: 13, fontWeight: 600 }}>
                          正在初始化本地离线算法引擎
                        </Text>
                        {/* 呼吸指示灯 */}
                        <span style={{
                          width: 6,
                          height: 6,
                          borderRadius: '50%',
                          background: CYAN,
                          boxShadow: `0 0 8px ${CYAN}`,
                          animation: 'pulse-icon 1s infinite ease-in-out'
                        }} />
                      </div>
                      
                      <div style={{
                        marginTop: 6,
                        padding: '8px 10px',
                        borderRadius: 6,
                        background: 'rgba(255, 255, 255, 0.015)',
                        border: '1px solid rgba(255, 255, 255, 0.02)'
                      }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                          <Text style={{ color: '#e0e6ed', fontSize: 12, fontWeight: 500 }}>
                            当前引擎: {modelInfo.modelName}
                          </Text>
                          <Text style={{ color: CYAN, fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}>
                            Offline Mode (100% 本地运行)
                          </Text>
                        </div>
                        <Text style={{ color: '#6b7b9d', fontSize: 11, display: 'block', lineHeight: 1.5 }}>
                          {modelInfo.modelDesc}
                        </Text>
                      </div>
                    </div>
                    <Spin size="small" style={{ color: '#a855f7', marginTop: 4 }} />
                  </div>
                )}
              </Card>
            )}

            {/* 情绪趋势图 */}
            {emotionCurve.length > 0 ? (
              <Card style={{
                background: 'rgba(255, 255, 255, 0.01)',
                borderColor: 'rgba(255, 255, 255, 0.05)', borderRadius: 12,
              }} title={<span style={{ color: '#e0e6ed', fontWeight: 600 }}>📊 情绪变化曲线</span>}>
                <EmotionCurve data={emotionCurve} height={200} />
              </Card>
            ) : (
              <Card style={{
                background: 'rgba(255, 255, 255, 0.01)',
                borderColor: 'rgba(255, 255, 255, 0.05)', borderRadius: 12,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '24px 0',
              }} title={<span style={{ color: '#e0e6ed', fontWeight: 600 }}>📊 情绪变化曲线</span>}>
                <Empty description={<span style={{ color: '#4a5a7a', fontSize: 12 }}>暂无情绪变化数据</span>} image={Empty.PRESENTED_IMAGE_SIMPLE} />
              </Card>
            )}

            {/* 任务队列 */}
            {analyzeTasks.length > 0 && (
              <Card
                style={{
                  background: 'rgba(255, 255, 255, 0.01)',
                  borderColor: 'rgba(255, 255, 255, 0.05)', borderRadius: 12,
                }}
                title={
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ color: '#e0e6ed', fontWeight: 600 }}>📋 分析队列调度</span>
                    <Button size="small" type="text" onClick={clearCompleted}
                      style={{ color: '#4a5a7a', fontSize: 12 }}>
                      清理已完成
                    </Button>
                  </div>
                }
              >
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {analyzeTasks.map(task => (
                    <AnalyzeTaskRow
                      key={task.id}
                      task={task}
                      onCancel={cancel}
                      onRetry={retry}
                      onRemove={remove}
                    />
                  ))}
                </div>
              </Card>
            )}

          </Space>
        </Col>

        {/* 右列：智能识别对白剧本 / 视频文案 */}
        <Col xs={24} lg={12}>
          <Card
            style={{
              background: 'rgba(255, 255, 255, 0.01)',
              borderColor: 'rgba(255, 255, 255, 0.05)',
              borderRadius: 12,
              height: '100%',
              display: 'flex',
              flexDirection: 'column',
            }}
            styles={{
              body: {
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                overflow: 'hidden',
                padding: '16px 20px',
              }
            }}
            title={
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ color: '#e0e6ed', fontWeight: 600 }}>📝 视频文案 (对白剧本 {asrSegments.length > 0 ? `${asrSegments.length} 段` : ''})</span>
                <Text style={{ color: '#4a5a7a', fontSize: 11 }}>悬停卡片可快速复制台词/时间轴</Text>
              </div>
            }
          >
            {asrSegments.length > 0 ? (
              <div
                className="subtitles-scroll"
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 12,
                  height: 'calc(100vh - 230px)',
                  overflowY: 'auto',
                  paddingRight: 6,
                }}
              >
                {asrSegments.map((seg, idx) => {
                  const spKey = seg.speaker || 'unknown';
                  const isSpeaker0 = spKey.includes('0');
                  const isSpeaker1 = spKey.includes('1');
                  
                  // 匹配精美 HSL 配色方案
                  const tagColor = isSpeaker0 ? CYAN : isSpeaker1 ? '#a855f7' : '#64748b';
                  const tagBg = isSpeaker0 ? 'rgba(0, 212, 255, 0.08)' : isSpeaker1 ? 'rgba(168, 85, 247, 0.08)' : 'rgba(100, 116, 139, 0.08)';

                  return (
                    <div
                      key={seg.id || idx}
                      className="dialogue-segment-card"
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 12,
                        padding: '12px 16px',
                        borderRadius: 8,
                        background: 'rgba(255, 255, 255, 0.015)',
                        border: '1px solid rgba(255, 255, 255, 0.03)',
                        borderLeft: `4px solid ${tagColor}`,
                        transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
                      }}
                    >
                      {/* 胶囊角色角色标志 */}
                      <div style={{ flexShrink: 0 }}>
                        <div style={{
                          padding: '4px 10px',
                          borderRadius: 12,
                          background: tagBg,
                          border: `1px solid ${tagColor}33`,
                          minWidth: 80,
                          textAlign: 'center',
                        }}>
                          <span style={{ fontSize: 10, fontWeight: 700, color: tagColor }}>
                            {spKey === 'unknown' ? '未知角色' : spKey.toUpperCase()}
                          </span>
                        </div>
                      </div>
                      
                      {/* 文本内容与时钟指示 */}
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <Text style={{ color: '#e2e8f0', fontSize: 13, lineHeight: '1.6', display: 'block' }}>
                          {seg.text}
                        </Text>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 6 }}>
                          <span style={{ fontSize: 11, color: '#4a5a7a' }}>⏱️</span>
                          <Text style={{ color: '#4a5a7a', fontSize: 10, fontFamily: "'JetBrains Mono', monospace" }}>
                            {seg.start.toFixed(2)}s ~ {seg.end.toFixed(2)}s
                          </Text>
                        </div>
                      </div>

                      {/* 右侧悬停操作区 */}
                      <div className="dialogue-actions" style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 4,
                        flexShrink: 0,
                      }}>
                        <Tooltip title="复制台词">
                          <Button
                            size="small"
                            shape="circle"
                            icon={<CopyOutlined />}
                            className="dialogue-action-btn"
                            onClick={() => handleCopyText(seg.text)}
                          />
                        </Tooltip>
                        <Tooltip title="复制时间轴">
                          <Button
                            size="small"
                            shape="circle"
                            icon={<ClockCircleOutlined />}
                            className="dialogue-action-btn"
                            onClick={() => handleCopyTimestamp(seg.start, seg.end)}
                          />
                        </Tooltip>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 400 }}>
                <Empty
                  description={
                    <span style={{ color: '#4a5a7a', fontSize: 13, textAlign: 'center', display: 'block' }}>
                      暂无识别到的台词旁白内容。<br />
                      请在左侧点击【开始分析】以获取视频文案。
                    </span>
                  }
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                />
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
};

export default AnalyzePanel;
