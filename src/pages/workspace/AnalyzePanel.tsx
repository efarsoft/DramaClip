/**
 * AI 分析面板 — 项目工作区 Step 2
 * 集成任务队列，支持排队、重试、取消
 */
import React, { useMemo } from 'react';
import {
  Typography,
  Button,
  Progress,
  Card,
  Table,
  Alert,
  Spin,
  Space,
  Empty,
  Tag,
  Tooltip,
  message,
} from 'antd';
import {
  PlayCircleOutlined,
  StopOutlined,
  CheckCircleFilled,
  ReloadOutlined,
  ClockCircleOutlined,
  LoadingOutlined,
  CloseCircleOutlined,
  MinusCircleOutlined,
} from '@ant-design/icons';
import { useProjectStore } from '../../stores/projectStore';
import { useTaskQueueStore, type Task } from '../../stores/taskQueueStore';
import { EmotionCurve } from '../../components/chart/EmotionCurve';

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
  asr?: { segments: ASRSegment[] };
  emotion?: { emotion_curve: EmotionPoint[] };
  highlights?: unknown[];
}

const PHASE_LABELS: Record<string, string> = {
  asr: '语音识别',
  emotion: '情绪分析',
  highlight: '高光识别',
  completed: '分析完成',
  failed: '分析失败',
  idle: '准备就绪',
};

// ── 分析任务状态标签 ──

const StatusTag: React.FC<{ status: Task['status'] }> = ({ status }) => {
  const map: Record<Task['status'], { color: string; icon: React.ReactNode; label: string }> = {
    queued: { color: '#6b7b9d', icon: <ClockCircleOutlined />, label: '排队中' },
    running: { color: CYAN, icon: <LoadingOutlined />, label: '分析中' },
    completed: { color: '#10b981', icon: <CheckCircleFilled />, label: '已完成' },
    failed: { color: '#ef4444', icon: <CloseCircleOutlined />, label: '失败' },
    cancelled: { color: '#f59e0b', icon: <MinusCircleOutlined />, label: '已取消' },
  };
  const m = map[status];
  return (
    <Tag style={{ borderRadius: 6, margin: 0, color: m.color, borderColor: `${m.color}44`, background: `${m.color}11` }}>
      {m.icon} {m.label}
    </Tag>
  );
};

// ── 单条分析任务行 ──

const AnalyzeTaskRow: React.FC<{
  task: Task;
  onCancel: (id: string) => void;
  onRetry: (id: string) => void;
  onRemove: (id: string) => void;
}> = ({ task, onCancel, onRetry, onRemove }) => {
  const { activeTaskId } = useTaskQueueStore();
  const isActive = task.id === activeTaskId;

  return (
    <div
      style={{
        display: 'flex', alignItems: 'center', gap: 12,
        padding: '8px 12px', borderRadius: 8,
        background: isActive ? 'rgba(0,212,255,0.04)' : 'transparent',
        border: `1px solid ${isActive ? `${CYAN}22` : 'transparent'}`,
        transition: 'all 0.2s',
      }}
    >
      <div style={{ flexShrink: 0, width: 72 }}>
        <StatusTag status={task.status} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
          <Text style={{ color: '#e0e6ed', fontSize: 13, fontWeight: 500 }}>项目分析</Text>
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
          <Text style={{ color: '#ef4444', fontSize: 11 }}>{task.error}</Text>
        )}
        {task.status === 'queued' && (
          <Text style={{ color: '#4a5a7a', fontSize: 11 }}>
            {new Date(task.createdAt).toLocaleTimeString('zh-CN')} 加入
          </Text>
        )}
      </div>
      <div style={{ flexShrink: 0, display: 'flex', gap: 4 }}>
        {task.status === 'running' && (
          <Tooltip title="取消">
            <Button size="small" shape="circle" icon={<StopOutlined />} onClick={() => onCancel(task.id)}
              style={{ border: 'none', color: '#f59e0b' }} />
          </Tooltip>
        )}
        {task.status === 'failed' && (
          <Tooltip title="重试">
            <Button size="small" shape="circle" icon={<ReloadOutlined />} onClick={() => onRetry(task.id)}
              style={{ border: 'none', color: CYAN }} />
          </Tooltip>
        )}
        {(task.status === 'completed' || task.status === 'cancelled') && (
          <Tooltip title="移除">
            <Button size="small" shape="circle" icon={<MinusCircleOutlined />} onClick={() => onRemove(task.id)}
              style={{ border: 'none', color: '#4a5a7a' }} />
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
  const { currentProject, selectedEpisodeIds } = useProjectStore();
  const { tasks: allTasks, activeTaskId, enqueue, cancel, retry, remove, clearCompleted, isRunning } = useTaskQueueStore();

  // 只取 analyze 类型任务
  const analyzeTasks = useMemo(
    () => allTasks.filter(t => t.type === 'analyze'),
    [allTasks],
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

  // 提取分析结果
  const analysisResults: AnalysisResults | undefined = latestCompleted?.results as AnalysisResults | undefined;
  const asrSegments: ASRSegment[] = analysisResults?.asr?.segments ?? [];
  const emotionCurve: EmotionPoint[] = analysisResults?.emotion?.emotion_curve ?? [];

  // 是否有分析结果可展示
  const hasResults = latestCompleted || analyzeTasks.some(t => t.status === 'completed');

  // ── 启动分析 ──
  const handleStart = () => {
    if (!currentProject) return;
    const ids = selectedEpisodeIds.length > 0 ? selectedEpisodeIds : [];
    if (ids.length === 0) {
      message.warning('请先在导入页面选择要分析的视频');
      return;
    }
    // 为每个选中的 episode 单独入队（后端为每个 episode 创建独立任务）
    ids.forEach(episodeId => {
      enqueue('analyze', currentProject.id, {
        project_id: currentProject.id,
        episode_ids: [episodeId],
      });
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
    <div style={{ maxWidth: 720, margin: '0 auto', padding: '32px 24px' }}>
      {/* ─── 标题区 ─── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <Title level={3} style={{ color: '#e0e6ed', margin: 0 }}>🤖 AI 智能分析</Title>
          <Text style={{ color: '#4a5a7a', fontSize: 13 }}>
            {currentProject.name} · 自动识别语音、情绪与高光片段
          </Text>
        </div>
        <Space>
          {!activeAnalyze ? (
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              onClick={handleStart}
              disabled={isRunning}
              style={{
                borderRadius: 8, height: 40, padding: '0 24px',
                background: `linear-gradient(135deg, ${CYAN}, ${PURPLE})`,
                border: 'none', fontWeight: 600,
                boxShadow: `0 0 20px ${CYAN}33`,
              }}
            >
              {isRunning ? '队列执行中...' : '开始分析'}
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
              }}
            >
              查看方案
            </Button>
          )}
        </Space>
      </div>

      {/* ─── 当前运行进度 ─── */}
      {activeAnalyze && (
        <Card style={{ marginBottom: 16, background: 'rgba(0,212,255,0.03)', borderColor: `${CYAN}22`, borderRadius: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <Spin size="small" style={{ color: CYAN }} />
            <div style={{ flex: 1 }}>
              <Text strong style={{ color: '#e0e6ed' }}>
                {PHASE_LABELS[activeAnalyze.phase] || activeAnalyze.phase || '处理中'}
              </Text>
            </div>
            <Text style={{ color: CYAN, fontFamily: "'JetBrains Mono', monospace" }}>{activeAnalyze.progress}%</Text>
          </div>
          <Progress
            percent={activeAnalyze.progress}
            strokeColor={{ '0%': '#108ee9', '100%': '#87d068' }}
            style={{ marginTop: 8, borderRadius: 4 }}
          />
        </Card>
      )}

      {/* ─── ASR 结果（来自后端真实数据） ─── */}
      {asrSegments.length > 0 && (
        <Card style={{
          marginBottom: 16, background: 'rgba(255,255,255,0.02)',
          borderColor: 'rgba(255,255,255,0.06)', borderRadius: 12,
        }} title={<span style={{ color: '#e0e6ed' }}>📝 语音识别结果</span>}>
          <Table
            dataSource={asrSegments}
            size="small"
            bordered
            rowKey={(record) => record.id}
            pagination={false}
            columns={[
              { title: '开始', dataIndex: 'start', width: 80, render: (v: number) => `${v.toFixed(1)}s` },
              { title: '结束', dataIndex: 'end', width: 80, render: (v: number) => `${v.toFixed(1)}s` },
              { title: '台词', dataIndex: 'text', key: 'text' },
              { title: '角色', dataIndex: 'speaker', width: 90 },
            ]}
          />
        </Card>
      )}

      {emotionCurve.length > 0 && (
        <Card style={{
          background: 'rgba(255,255,255,0.02)',
          borderColor: 'rgba(255,255,255,0.06)', borderRadius: 12,
        }} title={<span style={{ color: '#e0e6ed' }}>📊 情绪曲线</span>}>
          <EmotionCurve data={emotionCurve} height={200} />
        </Card>
      )}

      {/* ─── 分析队列 ─── */}
      {analyzeTasks.length > 0 && (
        <Card
          style={{
            marginTop: 16, background: 'rgba(255,255,255,0.02)',
            borderColor: 'rgba(255,255,255,0.06)', borderRadius: 12,
          }}
          title={
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ color: '#e0e6ed' }}>📋 分析队列</span>
              <Button size="small" type="text" onClick={clearCompleted}
                style={{ color: '#4a5a7a', fontSize: 12 }}>
                清理已完成
              </Button>
            </div>
          }
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
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
    </div>
  );
};

export default AnalyzePanel;
