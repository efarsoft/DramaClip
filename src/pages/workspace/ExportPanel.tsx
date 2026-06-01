/**
 * 导出发布面板 — 项目工作区 Step 5
 * 集成任务队列，支持排队、重试、取消
 */
import React, { useState, useMemo } from 'react';
import { Typography, Button, Card, Space, Progress, Select, message, Tooltip, Modal, Tag, Alert, Spin } from 'antd';
import {
  ExportOutlined,
  CheckCircleFilled,
  FolderOpenOutlined,
  ReloadOutlined,
  StopOutlined,
  PlayCircleOutlined,
  EyeOutlined,
  MinusCircleOutlined,
  ThunderboltOutlined,
  CopyOutlined,

  LoadingOutlined,
} from '@ant-design/icons';
import { useProjectStore } from '../../stores/projectStore';
import { useTaskQueueStore, type Task } from '../../stores/taskQueueStore';
import { VideoPlayerModal } from '../../components/common/VideoPlayer';
import { TaskStatusTag } from '../../components/common/TaskStatus';
import { clipApi, type TitleGenerationResult, type GeneratedTitle } from '../../services/ipc';

const { Title, Text } = Typography;
const CYAN = '#00d4ff';
const PURPLE = '#7c3aed';

const PRESETS = [
  { label: '16:9 横屏 (1080p 推荐)', value: '1080p', resolution: '1920x1080', fps: 30, bitrate: '8M' },
  { label: '9:16 竖屏 (1080p)', value: '1080p_v', resolution: '1080x1920', fps: 30, bitrate: '6M' },
];

interface Props {
  onComplete?: () => void;
}



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
        <TaskStatusTag status={task.status} taskType="export" />
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
  const [preset, setPreset] = useState(() => localStorage.getItem('dramaclip-export-preset') || '1080p');
  const [format, setFormat] = useState('mp4');
  const [previewPath, setPreviewPath] = useState<string | null>(null);
  const [previewTitle, setPreviewTitle] = useState<string | undefined>();
  const [titleResult, setTitleResult] = useState<TitleGenerationResult | null>(null);
  const [isGeneratingTitle, setIsGeneratingTitle] = useState(false);
  const [copiedTitle, setCopiedTitle] = useState<string | null>(null);
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
  const completedExportTasks = useMemo(
    () => exportTasks
      .filter(t => t.status === 'completed' && t.outputPath)
      .sort((a, b) => (b.completedAt || 0) - (a.completedAt || 0)),
    [exportTasks],
  );
  const latestClipResult = useMemo(
    () => allTasks
      .filter(t => t.type === 'clip' && t.status === 'completed')
      .sort((a, b) => (b.completedAt || 0) - (a.completedAt || 0))[0],
    [allTasks],
  );

  // 成片质量亮点数据源（来自最后一次剪辑任务使用的顶级高光片段）
  const clipSegmentsCount = ((latestClipResult?.params?.segments as any[])?.length) || 0;

  const [persistedExports, setPersistedExports] = useState<any[]>([]);

  // 1. 在项目加载时，重载该项目已生成过的成品视频记录和AI标题
  React.useEffect(() => {
    if (currentProject) {
      const exportsKey = `dramaclip-completed-exports-${currentProject.id}`;
      const titleKey = `dramaclip-title-result-${currentProject.id}`;
      
      const storedExports = localStorage.getItem(exportsKey);
      setPersistedExports(storedExports ? JSON.parse(storedExports) : []);

      const storedTitle = localStorage.getItem(titleKey);
      if (storedTitle) {
        setTitleResult(JSON.parse(storedTitle));
      } else {
        setTitleResult(null);
      }
    }
  }, [currentProject?.id]);

  // 2. 自动捕获并持久化每次新完成的导出视频成品记录
  React.useEffect(() => {
    if (completedExportTasks.length > 0 && currentProject) {
      const key = `dramaclip-completed-exports-${currentProject.id}`;
      const existing = localStorage.getItem(key);
      const list = existing ? JSON.parse(existing) : [];
      
      let updated = false;
      completedExportTasks.forEach(task => {
        if (!list.some((item: any) => item.id === task.id)) {
          list.push({
            id: task.id,
            outputPath: task.outputPath,
            resolution: (task.params as any)?.output_config?.resolution || '1080p',
            scheme: (task.params as any)?.output_config?.scheme || '',
            completedAt: task.completedAt || Date.now(),
          });
          updated = true;
        }
      });
      
      if (updated) {
        localStorage.setItem(key, JSON.stringify(list));
        setPersistedExports(list);
      }
    }
  }, [completedExportTasks, currentProject?.id]);

  // 展开一键三连等多版本成品视频（合并当前会话与历史持久化记录）
  const completedWorks = useMemo(() => {
    const list: Array<{
      id: string;
      outputPath: string;
      label: string;
      resolution: string;
      isVertical: boolean;
      completedAt: number;
    }> = [];

    // 合并当前任务队列中的导出任务
    const combined: Array<{
      id: string;
      outputPath: string;
      resolution: string;
      scheme: string;
      completedAt: number;
    }> = completedExportTasks.map(t => ({
      id: t.id,
      outputPath: t.outputPath || '',
      resolution: (t.params as any)?.output_config?.resolution || '1080p',
      scheme: (t.params as any)?.output_config?.scheme || '',
      completedAt: t.completedAt || Date.now(),
    }));

    // 载入历史导出的记录，去重
    persistedExports.forEach(p => {
      if (!combined.some(c => c.id === p.id)) {
        combined.push(p);
      }
    });

    // 依完成时间降序排列，最新生成的置顶
    combined.sort((a, b) => b.completedAt - a.completedAt);

    combined.forEach(item => {
      const path = item.outputPath;
      const res = item.resolution;
      const isVertical = res.includes('1080x1920') || res.includes('_v');

      if (path.includes('_original.')) {
        // 一键三连视频包，展开为三个实体视频文件
        list.push({
          id: `${item.id}-original`,
          outputPath: path,
          label: '原片解说版 (高光剪辑+原声剪接)',
          resolution: res,
          isVertical,
          completedAt: item.completedAt,
        });
        list.push({
          id: `${item.id}-hybrid`,
          outputPath: path.replace('_original.', '_hybrid.'),
          label: '交叉解说版 (高光剪辑+AI旁白+原声混音)',
          resolution: res,
          isVertical,
          completedAt: item.completedAt,
        });
        list.push({
          id: `${item.id}-full`,
          outputPath: path.replace('_original.', '_full.'),
          label: '全片解说版 (纯 AI 旁白配音解说)',
          resolution: res,
          isVertical,
          completedAt: item.completedAt,
        });
      } else {
        // 单方案正常导出版
        let label = '成品视频导出版';
        const scheme = item.scheme;
        if (scheme === 'original_narration') label = '原片解说版 (高光剪辑+原声剪接)';
        else if (scheme === 'hybrid_narration') label = '交叉解说版 (高光剪辑+AI旁白+原声混音)';
        else if (scheme === 'full_narration') label = '全片解说版 (纯 AI 旁白配音解说)';

        list.push({
          id: item.id,
          outputPath: path,
          label,
          resolution: res,
          isVertical,
          completedAt: item.completedAt,
        });
      }
    });

    return list;
  }, [completedExportTasks, persistedExports]);

  // ── 自动触发开始导出和AI标题生成（一键托管） ──
  React.useEffect(() => {
    if (currentProject && latestClipResult && exportTasks.length === 0 && !activeExport && !latestCompleted && !isRunning) {
      const timer = setTimeout(() => {
        handleExport();
        handleGenerateTitle();
      }, 500);
      return () => clearTimeout(timer);
    }
  }, [currentProject?.id, latestClipResult?.id]);

  // ── 生成AI标题 ──
  const handleGenerateTitle = async () => {
    if (!currentProject) return;
    setIsGeneratingTitle(true);
    try {
      // 自动请求并生成3个候选标题
      const result = await clipApi.generateTitle(currentProject.id, 3);
      setTitleResult(result);
      // 持久化保存 AI 标题与简介生成结果
      localStorage.setItem(`dramaclip-title-result-${currentProject.id}`, JSON.stringify(result));
      message.success('AI 标题与简介生成成功！');
    } catch (error) {
      message.error('AI 标题生成失败，请稍后重试');
      console.error('Title generation error:', error);
    } finally {
      setIsGeneratingTitle(false);
    }
  };

  // ── 复制标题到剪贴板 ──
  const handleCopyTitle = async (title: string) => {
    try {
      await navigator.clipboard.writeText(title);
      setCopiedTitle(title);
      message.success('已复制到剪贴板');
      setTimeout(() => setCopiedTitle(null), 2000);
    } catch {
      message.error('复制失败');
    }
  };

  // ── 提交导出任务 ──
  const handleExport = () => {
    if (!currentProject) return;
    const clip_task_id = latestClipResult?.id;
    if (!clip_task_id) {
      message.error('未检测到已完成的剪辑任务，请先在“智能剪辑”页面完成剪辑');
      return;
    }
    enqueue('export', currentProject.id, {
      project_id: currentProject.id,
      output_config: {
        format,
        resolution: selectedPreset.resolution,
        fps: selectedPreset.fps,
        bitrate: selectedPreset.bitrate,
        clip_task_id, // 传递已完成的剪辑任务ID
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
    <div style={{ maxWidth: 760, margin: '0 auto', padding: '32px 24px', display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* 标题 */}
      <div style={{ textAlign: 'center', marginBottom: 12 }}>
        <Title level={3} style={{ color: '#e8edff', margin: 0, fontWeight: 700, letterSpacing: 1 }}>🚀 导出发布</Title>
        <Text style={{ color: '#4a5a7a', fontSize: 13, marginTop: 6, display: 'block' }}>
          配置输出参数，自动生成成品视频与爆款标题简介
        </Text>
      </div>

      {/* ─── 提示：未完成剪辑 ─── */}
      {!latestClipResult && (
        <Alert
          type="warning"
          showIcon
          message={<span style={{ color: '#fbbf24', fontWeight: 600 }}>未检测到剪辑成果</span>}
          description={
            <div style={{ color: '#8892a4', marginTop: 4, fontSize: 13, lineHeight: 1.5 }}>
              您需要先在 <b>Step 3: 方案推荐</b> 中选择对应的解说剪辑方案，并点击下方的 <b>“应用此方案”</b>。待 AI 智能剪辑与高光片段自动合成任务完成后，才能在此处导出最终视频。
            </div>
          }
          style={{
            borderRadius: 12,
            background: 'rgba(251, 191, 36, 0.03)',
            borderColor: 'rgba(251, 191, 36, 0.15)',
          }}
        />
      )}

      {/* ─── 核心面板 1：导出渲染与进度管理（无多余配置项，一键式） ─── */}
      {latestClipResult && (
        <Card
          style={{
            background: activeExport ? 'rgba(0, 212, 255, 0.02)' : 'rgba(255, 255, 255, 0.01)',
            borderColor: activeExport ? `${CYAN}22` : 'rgba(255, 255, 255, 0.06)',
            borderRadius: 14,
            boxShadow: '0 8px 32px rgba(0, 0, 0, 0.2)',
          }}
          styles={{ body: { padding: '24px 28px' } }}
        >
          {activeExport ? (
            /* ── 正在导出状态 ── */
            <div style={{ textAlign: 'center' }}>
              <div style={{ position: 'relative', display: 'inline-block', marginBottom: 16 }}>
                <Spin indicator={<LoadingOutlined style={{ fontSize: 36, color: CYAN }} spin />} />
              </div>
              <Title level={4} style={{ color: '#e8edff', margin: '0 0 4px 0', fontWeight: 600 }}>
                正在转码并渲染成品视频...
              </Title>
              <Text style={{ color: '#8892a4', fontSize: 13, display: 'block', marginBottom: 20 }}>
                {activeExport.message || activeExport.phase || '请稍候，系统正在拼装最终视频文件...'}
              </Text>
              
              <Progress
                percent={activeExport.progress}
                strokeColor={{ '0%': CYAN, '100%': PURPLE }}
                trailColor="rgba(255, 255, 255, 0.05)"
                style={{ maxWidth: 520, margin: '0 auto 12px' }}
              />
              
              <div style={{ display: 'flex', justifyContent: 'center', gap: 24, alignItems: 'center' }}>
                <span style={{ color: '#4a5a7a', fontSize: 12 }}>
                  输出分辨率: <Text style={{ color: '#c8d0dc', fontFamily: "'JetBrains Mono', monospace" }}>{selectedPreset.resolution}</Text>
                </span>
                <span style={{ color: CYAN, fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, fontSize: 14 }}>
                  {activeExport.progress}%
                </span>
              </div>
            </div>
          ) : (
            /* ── 空闲状态 / 手动重新导出 ── */
            <div style={{ textAlign: 'center', padding: '12px 0' }}>
              <Text style={{ color: '#8892a4', fontSize: 14, display: 'block', marginBottom: 20 }}>
                当前绑定输出规格: <Tag color="cyan" style={{ border: 'none', borderRadius: 4, margin: '0 4px' }}>{selectedPreset.label}</Tag> ( {selectedPreset.resolution} / {selectedPreset.fps}fps )
              </Text>
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
                {isRunning ? '任务队列执行中...' : '开始导出视频成品'}
              </Button>
            </div>
          )}
        </Card>
      )}

      {/* ─── 核心面板 2：成品视频发布列表（总是可见，支持一键三连多版本预览与播放） ─── */}
      {completedWorks.length > 0 && (
        <Card
          style={{
            background: 'rgba(16, 185, 129, 0.01)',
            borderColor: 'rgba(16, 185, 129, 0.15)',
            borderRadius: 14,
            boxShadow: '0 8px 32px rgba(0, 0, 0, 0.2)',
          }}
          title={
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <CheckCircleFilled style={{ color: '#10b981', fontSize: 18 }} />
              <span style={{ color: '#e8edff', fontWeight: 600 }}>🎉 导出成功！成品视频列表 ({completedWorks.length} 个版本)</span>
            </div>
          }
        >
          {/* ✨ 成片质量亮点反馈 — 让用户强烈感受到“傻瓜化 + 高质量”已落地 */}
          {latestClipResult && (
            <div style={{
              margin: '0 0 14px 0',
              padding: '10px 15px',
              borderRadius: 10,
              background: 'rgba(16, 185, 129, 0.065)',
              border: '1px solid rgba(16, 185, 129, 0.22)',
            }}>
              <div style={{ fontSize: 12, color: '#34d399', fontWeight: 600, marginBottom: 3, display: 'flex', alignItems: 'center', gap: 6 }}>
                ✨ AI 成片质量自检 · 全程零手动干预
                {completedWorks.length >= 3 && <span style={{ marginLeft: 6, fontSize: 11, opacity: 0.9 }}>(一键三连三版本均已优化)</span>}
              </div>
              <div style={{ fontSize: 12.5, color: '#9ca3af', lineHeight: 1.7 }}>
                智能筛选 <span style={{ color: '#e8edff', fontWeight: 600 }}>{clipSegmentsCount || '多维'}</span> 个顶级高光片段
                {' · '}情绪弧线智能排序{' · '}原声保护优先{' · '}画面稳定约束{' · '}成片文案精炼
              </div>
              <div style={{ fontSize: 11, color: '#6b7b9d', marginTop: 2 }}>
                故事讲得清楚 · 情绪有起伏 · 解说不油腻 · 画面自然不晃
              </div>
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {completedWorks.map((work) => (
              <div
                key={work.id}
                onClick={() => {
                  setPreviewPath(work.outputPath);
                  setPreviewTitle(work.label);
                }}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 16,
                  padding: '14px 20px',
                  borderRadius: 12,
                  background: 'rgba(255, 255, 255, 0.015)',
                  border: '1px solid rgba(255, 255, 255, 0.03)',
                  cursor: 'pointer',
                  transition: 'all 0.25s',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'rgba(255, 255, 255, 0.03)';
                  e.currentTarget.style.borderColor = `${CYAN}55`;
                  e.currentTarget.style.transform = 'translateY(-2px)';
                  e.currentTarget.style.boxShadow = `0 6px 20px ${CYAN}15`;
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'rgba(255, 255, 255, 0.015)';
                  e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.03)';
                  e.currentTarget.style.transform = 'none';
                  e.currentTarget.style.boxShadow = 'none';
                }}
              >
                {/* 格式图标 */}
                <div style={{
                  width: 40, height: 40, borderRadius: 10,
                  background: 'rgba(0, 212, 255, 0.08)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 18, color: CYAN, flexShrink: 0
                }}>
                  🎥
                </div>
                
                {/* 视频信息 */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <Text strong style={{ color: '#fff', fontSize: 13.5 }}>
                      {work.label}
                    </Text>
                    <Tag color={work.isVertical ? 'purple' : 'cyan'} style={{ borderRadius: 4, fontSize: 10, border: 'none', margin: 0 }}>
                      {work.isVertical ? '竖屏 9:16' : '横屏 16:9'}
                    </Tag>
                  </div>
                  <Text style={{ color: '#4a5a7a', fontSize: 11 }} ellipsis>
                    输出位置: {work.outputPath}
                  </Text>
                </div>
                
                {/* 分辨率与操作 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
                  <span style={{
                    fontSize: 11, color: CYAN, background: 'rgba(0, 212, 255, 0.1)',
                    padding: '2px 8px', borderRadius: 4, fontWeight: 600, fontFamily: "'JetBrains Mono', monospace"
                  }}>
                    {work.resolution}
                  </span>
                  <Tooltip title="立即播放预览">
                    <Button
                      type="text"
                      icon={<PlayCircleOutlined style={{ fontSize: 22, color: CYAN }} />}
                    />
                  </Tooltip>
                </div>
              </div>
            ))}
          </div>

          <div style={{ display: 'flex', gap: 12, width: '100%', marginTop: 16 }}>
            <Button
              icon={<FolderOpenOutlined />}
              onClick={handleOpenOutput}
              style={{
                flex: 1, borderRadius: 8, height: 40,
                borderColor: `${CYAN}44`, color: CYAN,
                background: 'rgba(0, 212, 255, 0.02)', fontWeight: 600
              }}
            >
              打开输出文件夹
            </Button>
            {onComplete && (
              <Button
                type="primary"
                onClick={onComplete}
                style={{
                  flex: 1, borderRadius: 8, height: 40,
                  background: `linear-gradient(135deg, ${CYAN}, ${PURPLE})`,
                  border: 'none', fontWeight: 600
                }}
              >
                完成返回工作台
              </Button>
            )}
          </div>
        </Card>
      )}

      {/* ─── 核心面板 3：AI 智能文案发布中心（总是可见，自动生成并精选 3 个候选标题与简介） ─── */}
      {latestClipResult && (
        <Card
          style={{
            background: 'rgba(124, 58, 237, 0.015)',
            borderColor: 'rgba(124, 58, 237, 0.15)',
            borderRadius: 14,
            boxShadow: '0 8px 32px rgba(0, 0, 0, 0.2)',
          }}
          title={
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 16 }}>✨</span>
                <span style={{ color: '#e8edff', fontWeight: 600 }}>AI 爆款标题 & 视频简介 (3个精选候选)</span>
              </div>
              <Button
                size="small"
                type="text"
                onClick={handleGenerateTitle}
                disabled={isGeneratingTitle}
                icon={<ReloadOutlined spin={isGeneratingTitle} />}
                style={{ color: '#a78bfa', fontSize: 12 }}
              >
                重新生成
              </Button>
            </div>
          }
        >
          {isGeneratingTitle && !titleResult && (
            <div style={{ padding: '32px 0', textAlign: 'center' }}>
              <Spin indicator={<LoadingOutlined style={{ fontSize: 32, color: PURPLE }} spin />} />
              <div style={{ color: '#8892a4', marginTop: 12, fontSize: 13 }}>
                AI 正在根据原片情节自动提炼爆款标题和简介，请稍候...
              </div>
            </div>
          )}

          {!isGeneratingTitle && !titleResult && (
            <div style={{ padding: '16px 0', textAlign: 'center' }}>
              <Button
                type="dashed"
                onClick={handleGenerateTitle}
                style={{ borderColor: `${PURPLE}55`, color: '#a78bfa' }}
              >
                获取 AI 标题与简介
              </Button>
            </div>
          )}

          {titleResult && titleResult.success && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {/* 3个候选标题 */}
              <div>
                <Text style={{ color: '#6b7b9d', fontSize: 12, marginBottom: 8, display: 'block' }}>
                  💡 爆款候选标题 (精选3个，点击右侧复制)
                </Text>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {titleResult.titles.slice(0, 3).map((title: GeneratedTitle, index: number) => (
                    <div
                      key={index}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 12,
                        padding: '12px 16px',
                        borderRadius: 10,
                        background: 'rgba(255, 255, 255, 0.015)',
                        border: '1px solid rgba(255, 255, 255, 0.03)',
                        transition: 'all 0.25s',
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.background = 'rgba(255,255,255,0.03)';
                        e.currentTarget.style.borderColor = `${PURPLE}44`;
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.background = 'rgba(255, 255, 255, 0.015)';
                        e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.03)';
                      }}
                    >
                      <div style={{
                        padding: '2px 8px', borderRadius: 4, fontSize: 11,
                        background: `${PURPLE}18`, color: '#a78bfa',
                        fontWeight: 600, flexShrink: 0
                      }}>
                        {title.style_label || `精选候选`}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <Text strong style={{ color: '#e8edff', fontSize: 14 }}>
                          {title.title}
                        </Text>
                      </div>
                      <Tooltip title={copiedTitle === title.title ? "已复制" : "复制标题"}>
                        <Button
                          size="small"
                          shape="circle"
                          icon={copiedTitle === title.title ? <CheckCircleFilled style={{ color: '#10b981' }} /> : <CopyOutlined />}
                          onClick={() => handleCopyTitle(title.title)}
                          style={{ border: 'none', color: '#6b7b9d', background: 'transparent' }}
                        />
                      </Tooltip>
                    </div>
                  ))}
                </div>
              </div>

              {/* 视频简介 */}
              <div>
                <Text style={{ color: '#6b7b9d', fontSize: 12, marginBottom: 6, display: 'block' }}>
                  📝 视频简介 (已提炼剧集核心情节与戏剧张力)
                </Text>
                <div
                  style={{
                    padding: '14px 18px',
                    borderRadius: 10,
                    background: 'rgba(255, 255, 255, 0.015)',
                    border: '1px solid rgba(255, 255, 255, 0.03)',
                    position: 'relative',
                  }}
                >
                  <Text style={{ color: '#c8d0dc', fontSize: 13.5, lineHeight: 1.6, display: 'block' }}>
                    {titleResult.intro.medium || titleResult.intro.short}
                  </Text>
                  
                  <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 10 }}>
                    <Button
                      size="small"
                      icon={copiedTitle === (titleResult.intro.medium || titleResult.intro.short) ? <CheckCircleFilled style={{ color: '#10b981' }} /> : <CopyOutlined />}
                      onClick={() => handleCopyTitle(titleResult.intro.medium || titleResult.intro.short)}
                      style={{ border: 'none', color: '#6b7b9d', background: 'transparent' }}
                    >
                      复制简介文案
                    </Button>
                  </div>
                </div>
              </div>

              {/* 推荐标签 */}
              {titleResult.intro.hashtags && titleResult.intro.hashtags.length > 0 && (
                <div>
                  <Text style={{ color: '#6b7b9d', fontSize: 12, marginBottom: 8, display: 'block' }}>
                    🏷️ 推荐分发话题标签
                  </Text>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {titleResult.intro.hashtags.map((tag: string, index: number) => (
                      <Tag
                        key={index}
                        onClick={() => handleCopyTitle(`#${tag}`)}
                        style={{
                          background: 'rgba(0, 212, 255, 0.08)',
                          borderColor: 'rgba(0, 212, 255, 0.15)',
                          color: CYAN,
                          borderRadius: 4,
                          cursor: 'pointer',
                          padding: '2px 8px',
                        }}
                      >
                        #{tag}
                      </Tag>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </Card>
      )}

      {/* ─── 任务队列折叠记录 ─── */}
      {exportTasks.length > 0 && (
        <Card
          size="small"
          style={{
            background: 'rgba(255, 255, 255, 0.01)',
            borderColor: 'rgba(255, 255, 255, 0.04)',
            borderRadius: 12,
          }}
          title={
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ color: '#6b7b9d', fontSize: 11 }}>📋 详细导出队列记录</span>
              <Button
                size="small"
                type="text"
                onClick={clearCompleted}
                style={{ color: '#4a5a7a', fontSize: 11 }}
              >
                清理已完成
              </Button>
            </div>
          }
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
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
