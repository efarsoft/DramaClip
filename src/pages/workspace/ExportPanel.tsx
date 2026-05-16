/**
 * 导出发布面板 — 项目工作区 Step 5
 * 集成任务队列，支持排队、重试、取消
 */
import React, { useState, useMemo } from 'react';
import { Typography, Button, Card, Space, Progress, Select, message, Tag, Tooltip, Modal } from 'antd';
import {
  ExportOutlined,
  CheckCircleFilled,
  FolderOpenOutlined,
  CloseCircleOutlined,
  ReloadOutlined,
  MinusCircleOutlined,
  LoadingOutlined,
  ClockCircleOutlined,
  StopOutlined,
  PlayCircleOutlined,
  EyeOutlined,
} from '@ant-design/icons';
import { useProjectStore } from '../../stores/projectStore';
import { useTaskQueueStore, type Task } from '../../stores/taskQueueStore';
import { VideoPlayerModal } from '../../components/common/VideoPlayer';

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

// ── 任务状态徽标 ──

const StatusTag: React.FC<{ status: Task['status'] }> = ({ status }) => {
  const map: Record<Task['status'], { color: string; icon: React.ReactNode; label: string }> = {
    queued: { color: '#6b7b9d', icon: <ClockCircleOutlined />, label: '排队中' },
    running: { color: CYAN, icon: <LoadingOutlined />, label: '导出中' },
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

// ── 单条任务行 ──

const TaskRow: React.FC<{ task: Task; onCancel: (id: string) => void; onRetry: (id: string) => void; onRemove: (id: string) => void; onPreview?: (path: string) => void }> = ({
  task,
  onCancel,
  onRetry,
  onRemove,
  onPreview,
}) => {
  const { activeTaskId } = useTaskQueueStore();
  const isActive = task.id === activeTaskId;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '8px 12px',
        borderRadius: 8,
        background: isActive ? 'rgba(0,212,255,0.04)' : 'transparent',
        border: `1px solid ${isActive ? `${CYAN}22` : 'transparent'}`,
        transition: 'all 0.2s',
      }}
    >
      {/* 状态 */}
      <div style={{ flexShrink: 0, width: 72 }}>
        <StatusTag status={task.status} />
      </div>

      {/* 进度 / 信息 */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
          <Text style={{ color: '#e0e6ed', fontSize: 13, fontWeight: 500 }} ellipsis>
            {task.type === 'export' ? '导出' : task.type}
          </Text>
          <Text style={{ color: '#4a5a7a', fontSize: 11 }}>{task.phase}</Text>
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

      {/* 操作 */}
      <div style={{ flexShrink: 0, display: 'flex', gap: 4 }}>
        {task.status === 'running' && (
          <Tooltip title="取消">
            <Button
              size="small"
              shape="circle"
              icon={<StopOutlined />}
              onClick={() => onCancel(task.id)}
              style={{ border: 'none', color: '#f59e0b' }}
            />
          </Tooltip>
        )}
        {task.status === 'failed' && (
          <Tooltip title="重试">
            <Button
              size="small"
              shape="circle"
              icon={<ReloadOutlined />}
              onClick={() => onRetry(task.id)}
              style={{ border: 'none', color: CYAN }}
            />
          </Tooltip>
        )}
        {(task.status === 'completed' || task.status === 'cancelled') && (
          <>
            {task.status === 'completed' && task.outputPath && onPreview && (
              <Tooltip title="预览视频">
                <Button
                  size="small"
                  shape="circle"
                  icon={<EyeOutlined />}
                  onClick={() => onPreview(task.outputPath!)}
                  style={{ border: 'none', color: CYAN }}
                />
              </Tooltip>
            )}
            <Tooltip title="移除">
              <Button
              size="small"
              shape="circle"
              icon={<MinusCircleOutlined />}
              onClick={() => onRemove(task.id)}
              style={{ border: 'none', color: '#4a5a7a' }}
            />
          </Tooltip>
          </>
        )}
      </div>
    </div>
  );
};

// ── 主面板 ──

const ExportPanel: React.FC<Props> = ({ onComplete }) => {
  const { currentProject } = useProjectStore();
  const [preset, setPreset] = useState('1080p');
  const [format, setFormat] = useState('mp4');
  const [previewPath, setPreviewPath] = useState<string | null>(null);
  const [previewTitle, setPreviewTitle] = useState<string | undefined>();
  const { tasks: allTasks, activeTaskId, enqueue, cancel, retry, remove, clearCompleted, isRunning } = useTaskQueueStore();
  const selectedPreset = PRESETS.find(p => p.value === preset) || PRESETS[0];

  // 只显示 export 类型的任务
  const exportTasks = useMemo(
    () => allTasks.filter(t => t.type === 'export'),
    [allTasks],
  );
  const activeExport = useMemo(
    () => exportTasks.find(t => t.id === activeTaskId),
    [exportTasks, activeTaskId],
  );
  const latestCompleted = useMemo(
    () => exportTasks
      .filter(t => t.status === 'completed')
      .sort((a, b) => (b.completedAt || 0) - (a.completedAt || 0))[0],
    [exportTasks],
  );

  // ── 提交导出任务 ──

  const handleExport = () => {
    if (!currentProject) return;
    enqueue('export', currentProject.id, {
      project_id: currentProject.id,
      output_config: {
        format,
        resolution: selectedPreset.resolution,
        fps: selectedPreset.fps,
        bitrate: selectedPreset.bitrate,
      },
    });
    message.success('已加入导出队列');
  };

  // ── 打开输出文件夹（取最近完成任务的输出路径） ──

  const handleOpenOutput = async () => {
    const completed = exportTasks
      .filter(t => t.status === 'completed' && t.outputPath)
      .sort((a, b) => (b.completedAt || 0) - (a.completedAt || 0))[0];
    const outPath = completed?.outputPath;
    if (outPath) {
      const dir = String(outPath).replace(/[/\\][^/\\]*$/, '');
      try {
        await window.electronAPI?.system?.openPath(dir);
      } catch {
        message.info('输出路径：' + dir);
      }
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

      {/* ── 配置区（有活跃任务时隐藏） ── */}
      {!activeExport ? (
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
          <div style={{ textAlign: 'center', marginBottom: 32 }}>
            <Button
              type="primary"
              size="large"
              onClick={handleExport}
              disabled={isRunning}
              icon={<ExportOutlined />}
              style={{
                height: 48, borderRadius: 10, padding: '0 48px',
                background: `linear-gradient(135deg, ${CYAN}, ${PURPLE})`,
                border: 'none', fontWeight: 600, fontSize: 15, letterSpacing: 1,
                boxShadow: `0 0 24px ${CYAN}33`,
              }}
            >
              {isRunning ? '队列执行中...' : '开始导出'}
            </Button>
            {exportTasks.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <Text style={{ color: '#4a5a7a', fontSize: 12 }}>
                  队列中有 {exportTasks.filter(t => t.status !== 'completed').length} 个待处理任务
                </Text>
              </div>
            )}
          </div>
        </>
      ) : (
        /* ── 当前任务进度 ── */
        <Card style={{
          marginBottom: 24,
          background: 'rgba(0,212,255,0.03)',
          borderColor: `${CYAN}22`, borderRadius: 12,
        }}>
          <div style={{ textAlign: 'center', marginBottom: 16 }}>
            <LoadingOutlined style={{ fontSize: 32, color: CYAN }} />
            <Title level={4} style={{ color: '#e0e6ed', margin: '8px 0 0' }}>正在导出...</Title>
            <Text style={{ color: '#4a5a7a', fontSize: 13 }}>{activeExport.phase}</Text>
          </div>
          <Progress
            percent={activeExport.progress}
            strokeColor={{ '0%': CYAN, '100%': PURPLE }}
            trailColor="rgba(255,255,255,0.05)"
          />
          <div style={{ marginTop: 12, textAlign: 'center' }}>
            <Text style={{ color: '#4a5a7a', fontSize: 13 }}>{activeExport.progress}%</Text>
          </div>
        </Card>
      )}

      {/* ── 已完成状态 ── */}
      {!activeExport && latestCompleted && (
        <Card style={{
          textAlign: 'center', padding: '40px 24px', marginBottom: 24,
          background: 'rgba(16,185,129,0.04)',
          borderColor: 'rgba(16,185,129,0.2)', borderRadius: 16,
        }}>
          <CheckCircleFilled style={{ fontSize: 64, color: '#10b981' }} />
          <Title level={3} style={{ color: '#e0e6ed', margin: '16px 0 8px' }}>导出完成！</Title>
          <Text style={{ color: '#4a5a7a' }}>视频已成功导出</Text>
          <div style={{ marginTop: 20, display: 'flex', justifyContent: 'center', gap: 12 }}>
            {latestCompleted.outputPath && (
              <Button
                icon={<PlayCircleOutlined />}
                onClick={() => { setPreviewPath(latestCompleted.outputPath!); setPreviewTitle('导出结果预览'); }}
                style={{ borderRadius: 8, height: 40, background: `linear-gradient(135deg, ${CYAN}, ${PURPLE})`, border: 'none', color: '#fff', fontWeight: 600 }}
              >
                预览视频
              </Button>
            )}
            <Button
              icon={<FolderOpenOutlined />}
              onClick={handleOpenOutput}
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

      {/* ── 任务队列列表 ── */}
      {exportTasks.length > 0 && (
        <Card
          style={{
            background: 'rgba(255,255,255,0.02)',
            borderColor: 'rgba(255,255,255,0.06)', borderRadius: 12,
          }}
          title={
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ color: '#e0e6ed' }}>📋 导出队列</span>
              <Space size={4}>
                <Button
                  size="small"
                  type="text"
                  onClick={clearCompleted}
                  style={{ color: '#4a5a7a', fontSize: 12 }}
                >
                  清理已完成
                </Button>
              </Space>
            </div>
          }
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {exportTasks.map(task => (
              <TaskRow
                key={task.id}
                task={task}
                onCancel={cancel}
                onRetry={retry}
                onRemove={remove}
                onPreview={(path) => { setPreviewPath(path); setPreviewTitle('导出结果预览'); }}
              />
            ))}
          </div>
        </Card>
      )}

      {/* ─── 导出视频预览模态框 ─── */}
      <VideoPlayerModal
        open={!!previewPath}
        onClose={() => { setPreviewPath(null); setPreviewTitle(undefined); }}
        filePath={previewPath ?? ''}
        title={previewTitle}
      />
    </div>
  );
};

export default ExportPanel;
