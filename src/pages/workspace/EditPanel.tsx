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
  LoadingOutlined,
  ClockCircleOutlined,
  StopOutlined,
  ReloadOutlined,
  CloseCircleOutlined,
  MinusCircleOutlined,
} from '@ant-design/icons';
import { useProjectStore } from '../../stores/projectStore';
import { useTaskQueueStore, type Task } from '../../stores/taskQueueStore';

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

const EMOTION_COLORS: Record<string, string> = {
  neutral: '#6b7b9d', joy: '#10b981', anger: '#ef4444', surprise: '#f59e0b', sad: '#6366f1',
};

// ── 剪辑任务状态标签 ──

const ClipStatusTag: React.FC<{ status: Task['status'] }> = ({ status }) => {
  const map: Record<Task['status'], { color: string; label: string }> = {
    queued: { color: '#6b7b9d', label: '排队中' },
    running: { color: CYAN, label: '剪辑中' },
    completed: { color: '#10b981', label: '剪辑完成' },
    failed: { color: '#ef4444', label: '失败' },
    cancelled: { color: '#f59e0b', label: '已取消' },
  };
  const m = map[status];
  return (
    <Tag style={{ borderRadius: 6, color: m.color, borderColor: `${m.color}44`, background: `${m.color}11` }}>
      {m.label}
    </Tag>
  );
};

interface Props {
  onNext: () => void;
}

const EditPanel: React.FC<Props> = ({ onNext }) => {
  const { currentProject } = useProjectStore();
  const [segments, setSegments] = useState(MOCK_SEGMENTS);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set(segments.map(s => s.id)));

  const { tasks: allTasks, activeTaskId, enqueue, cancel, retry, remove, clearCompleted } = useTaskQueueStore();

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
      segments: Array.from(selectedIds),
      mode: 'highlight',
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
    <div style={{ maxWidth: 760, margin: '0 auto', padding: '32px 24px' }}>
      {/* ─── 标题 ─── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
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

      {/* ─── 片段列表 ─── */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 24 }}>
        {segments.map((seg, idx) => {
          const selected = selectedIds.has(seg.id);
          return (
            <div
              key={seg.id}
              onClick={() => !isClipRunning && toggleSelect(seg.id)}
              style={{
                display: 'flex', alignItems: 'center', gap: 16,
                padding: '16px 20px', borderRadius: 12,
                background: selected ? `linear-gradient(135deg, ${CYAN}08, ${PURPLE}08)` : 'rgba(255,255,255,0.02)',
                border: selected ? `1px solid ${CYAN}44` : '1px solid rgba(255,255,255,0.05)',
                cursor: isClipRunning ? 'not-allowed' : 'pointer',
                transition: 'all 0.25s',
                opacity: selected ? 1 : 0.45,
              }}
            >
              {/* 序号 */}
              <span style={{
                width: 26, height: 26, borderRadius: 8, display: 'flex',
                alignItems: 'center', justifyContent: 'center',
                background: `rgba(255,255,255,0.06)`, color: '#4a5a7a',
                fontSize: 12, fontWeight: 600, fontFamily: "'JetBrains Mono', monospace",
              }}>{idx + 1}</span>

              {/* 标签 */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, color: '#e0e6ed', fontSize: 15, marginBottom: 2 }}>
                  {seg.label}
                </div>
                <Text ellipsis style={{ color: '#4a5a7a', fontSize: 13 }}>{seg.desc}</Text>
              </div>

              {/* 时长 */}
              <span style={{
                fontSize: 13, fontFamily: "'JetBrains Mono', monospace", color: '#6b7b9d', whiteSpace: 'nowrap',
              }}>
                {seg.duration.toFixed(1)}s
              </span>

              {/* 情绪 */}
              <div style={{
                padding: '2px 10px', borderRadius: 6, fontSize: 12,
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
          marginBottom: 24,
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

      {/* ─── 动作按钮区 ─── */}
      <div style={{ display: 'flex', justifyContent: 'center', gap: 12, flexWrap: 'wrap' }}>
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

      {/* ─── 剪辑队列表 ─── */}
      {clipTasks.length > 0 && (
        <Card
          style={{
            marginTop: 20, background: 'rgba(255,255,255,0.02)',
            borderColor: 'rgba(255,255,255,0.06)', borderRadius: 12,
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
                <ClipStatusTag status={task.status} />
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
    </div>
  );
};

export default EditPanel;
