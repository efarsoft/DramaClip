/**
 * 导入视频面板 — 项目工作区 Step 1
 * 卡片式视频列表，支持多选和导入
 */

import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, App, Typography, Empty, Space, Checkbox, Card, Spin, Tooltip } from 'antd';
import {
  FolderOpenOutlined,
  UploadOutlined,
  PlayCircleOutlined,
  DeleteOutlined,
  ReloadOutlined,
  EyeOutlined,
  FileOutlined,
} from '@ant-design/icons';
import { useProjectStore } from '../../stores/projectStore';
import type { Episode } from '../../services/ipc';
import { VideoPlayerModal, MiniPreview } from '../../components/common/VideoPlayer';

const { Title, Text } = Typography;

const CYAN = '#00d4ff';
const PURPLE = '#7c3aed';
const BG_DEEP = '#060a17';

interface Props {
  onNext: () => void;
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

const ImportPanel: React.FC<Props> = ({ onNext }) => {
  const { message } = App.useApp();
  const {
    currentProject,
    currentVideos,
    importVideos,
    loadProjectVideos,
    selectedEpisodeIds,
    setSelectedEpisodeIds,
  } = useProjectStore();
  const navigate = useNavigate();
  const [importing, setImporting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [previewVideo, setPreviewVideo] = useState<Episode | null>(null);
  const dragCounterRef = React.useRef(0);

  // 打开项目时加载视频列表，并显示同步结果
  const syncShownRef = React.useRef(false);
  useEffect(() => {
    if (currentProject && !syncShownRef.current) {
      syncShownRef.current = true;
      const sr = currentProject.sync_result;
      if (sr && (sr.found > 0 || sr.removed > 0)) {
        const parts: string[] = [];
        if (sr.found > 0) parts.push(`发现 ${sr.found} 个新视频`);
        if (sr.removed > 0) parts.push(`移除 ${sr.removed} 个已删除的视频`);
        if (sr.missing > 0) parts.push(`${sr.missing} 个文件缺失`);
        message.info(`项目同步完成：${parts.join('，')}`);
      }
    }
  }, [currentProject]);

  // 选择/取消选择视频
  const handleSelect = (id: string, checked: boolean) => {
    if (checked) {
      setSelectedEpisodeIds([...selectedEpisodeIds, id]);
    } else {
      setSelectedEpisodeIds(selectedEpisodeIds.filter((v) => v !== id));
    }
  };

  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedEpisodeIds(currentVideos.map((v) => v.id));
    } else {
      setSelectedEpisodeIds([]);
    }
  };

  // 拖拽导入（原生桌面拖拽）
  const handleDrop = useCallback(async (files: FileList | File[]) => {
    if (!currentProject || files.length === 0) return;
    
    // 开发环境（非 Electron 环境）路径检测与友好提示
    const invalidPaths = Array.from(files).filter((f: any) => !f.path);
    if (invalidPaths.length > 0 && !window.electronAPI) {
      message.warning('开发环境网页端拖拽无法获取完整绝对路径。请使用 Electron 客户端客户端，或点击“从文件夹选择”按钮导入。');
      return;
    }

    setImporting(true);
    try {
      const paths = Array.from(files).map((f: any) => f.path || f.name);
      const imported = await importVideos(currentProject.id, paths);
      if (imported && imported.length > 0) {
        message.success(`成功导入 ${imported.length} 个视频`);
      } else {
        message.warning('导入失败：未找到有效视频文件，或格式不受支持');
      }
    } catch (err: any) {
      message.error(err?.message || '导入失败');
    } finally {
      setImporting(false);
    }
  }, [currentProject, importVideos, message]);

  // 选择视频文件导入
  const handleSelectFiles = async () => {
    if (!currentProject) return;
    try {
      if (window.electronAPI?.dialog?.openFile) {
        const result = await window.electronAPI.dialog.openFile({
          properties: ['openFile', 'multiSelections'],
          filters: [
            { name: '视频文件', extensions: ['mp4', 'mov', 'avi', 'mkv', 'wmv', 'webm', 'flv'] },
            { name: '所有文件', extensions: ['*'] }
          ],
        });
        if (result.success && result.data && result.data.length > 0) {
          setImporting(true);
          try {
            const imported = await importVideos(currentProject.id, result.data);
            if (imported && imported.length > 0) {
              message.success(`成功导入 ${imported.length} 个视频`);
            } else {
              message.warning('导入失败：所选视频可能已存在、路径无效或格式不受支持');
            }
          } finally {
            setImporting(false);
          }
        }
      } else {
        message.info('开发环境：请通过拖拽导入视频');
      }
    } catch (err: any) {
      message.error(err?.message || '导入失败');
    }
  };

  // 选择视频文件夹导入
  const handleSelectFolder = async () => {
    if (!currentProject) return;
    try {
      if (window.electronAPI?.dialog?.openFile) {
        const result = await window.electronAPI.dialog.openFile({
          properties: ['openDirectory'],
        });
        if (result.success && result.data && result.data.length > 0) {
          setImporting(true);
          try {
            const imported = await importVideos(currentProject.id, result.data);
            if (imported && imported.length > 0) {
              message.success(`成功导入 ${imported.length} 个视频`);
            } else {
              message.warning('导入失败：所选文件夹内未找到有效视频');
            }
          } finally {
            setImporting(false);
          }
        }
      } else {
        message.info('开发环境：请通过拖拽导入视频');
      }
    } catch (err: any) {
      message.error(err?.message || '导入失败');
    }
  };

  // 刷新视频列表（重新扫描项目目录）
  const handleRefresh = async () => {
    if (!currentProject) return;
    setRefreshing(true);
    try {
      await loadProjectVideos(currentProject.id);
      message.success('视频列表已刷新');
    } catch (err: any) {
      message.error(err?.message || '刷新失败');
    } finally {
      setRefreshing(false);
    }
  };

  // 开始分析（直接启动分析并跳转到分析页面）
  const handleStartAnalysis = async () => {
    if (selectedEpisodeIds.length === 0) {
      message.warning('请至少选择一个视频进行分析');
      return;
    }
    if (!currentProject) return;
    
    // P4: 读取当前说话人分离偏好（支持 pyannote 高精度路径）
    let diarizationOptions: { use_pyannote_diarization?: boolean } | undefined;
    try {
      const { settingsApi } = await import('../../services/ipc');
      const fullSettings = await settingsApi.get();
      const engine = fullSettings?.diarization?.engine || 'clustering';
      if (engine === 'pyannote') {
        diarizationOptions = { use_pyannote_diarization: true };
      }
    } catch (e) {
      // 忽略，保持默认聚类模式
    }
    
    // 直接调用 analyze API 启动分析
    const { useTaskQueueStore } = await import('../../stores/taskQueueStore');
    const { enqueue } = useTaskQueueStore.getState();
    
    // 为每个选中的视频创建分析任务（携带 diarization options）
    selectedEpisodeIds.forEach(episodeId => {
      enqueue('analyze', currentProject.id, {
        project_id: currentProject.id,
        episode_ids: [episodeId],
        ...(diarizationOptions ? { options: diarizationOptions } : {}),
      });
    });
    
    message.success(`已添加 ${selectedEpisodeIds.length} 个分析任务${diarizationOptions ? '（pyannote 精准模式）' : ''}`);
    
    // 跳转到分析页面
    onNext();
  };

  // 无项目
  if (!currentProject) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <span style={{ color: '#6b7b9d' }}>
              请先选择或创建一个项目
              <br />
              <Button type="link" onClick={() => navigate('/')} style={{ color: CYAN, marginTop: 8 }}>
                返回工作台
              </Button>
            </span>
          }
        />
      </div>
    );
  }

  const allSelected = currentVideos.length > 0 && selectedEpisodeIds.length === currentVideos.length;

  // 智能排序：按文件名中的数字排序（支持中文数字和英文数字），极其鲁棒以防止属性缺失引起的渲染崩溃
  const sortedVideos = [...currentVideos].sort((a, b) => {
    if (!a || !b) return 0;
    const nameA = a.name || '';
    const nameB = b.name || '';
    const extractNumbers = (name: string): number[] => {
      const matches = name.match(/\d+/g);
      return matches ? matches.map(Number) : [];
    };
    const numsA = extractNumbers(nameA);
    const numsB = extractNumbers(nameB);
    
    // 逐个比较数字
    for (let i = 0; i < Math.min(numsA.length, numsB.length); i++) {
      if (numsA[i] !== numsB[i]) return numsA[i] - numsB[i];
    }
    
    // 数字数量不同，数字少的排前面
    if (numsA.length !== numsB.length) return numsA.length - numsB.length;
    
    // 数字相同，按字母顺序
    return nameA.localeCompare(nameB, 'zh-CN');
  });

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: '32px 24px', height: '100%', flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative' }}>
      {/* ─── 标题 ─── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24, flexShrink: 0 }}>
        <div>
          <Title level={3} style={{ color: '#e0e6ed', margin: 0 }}>🎬 导入视频素材</Title>
          <Text style={{ color: '#4a5a7a', fontSize: 13 }}>
            {currentProject.name} · 共 {currentVideos.length} 个视频
          </Text>
        </div>
      </div>

      {/* ─── 拖拽/选择导入区（原生桌面操作） ─── */}
      <div
        onDragEnter={(e) => {
          e.preventDefault();
          dragCounterRef.current += 1;
          if (!importing) setDragging(true);
        }}
        onDragLeave={(e) => {
          e.preventDefault();
          dragCounterRef.current -= 1;
          if (dragCounterRef.current === 0) setDragging(false);
        }}
        onDragOver={(e) => {
          e.preventDefault();
          e.dataTransfer.dropEffect = 'copy';
        }}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          dragCounterRef.current = 0;
          if (e.dataTransfer.files.length > 0) {
            handleDrop(e.dataTransfer.files);
          }
        }}
        onClick={() => {
          if (!importing) handleSelectFiles();
        }}
        style={{
          borderRadius: 16,
          marginBottom: 24,
          padding: 32,
          cursor: importing ? 'not-allowed' : 'pointer',
          background: dragging
            ? `linear-gradient(135deg, ${CYAN}18, ${PURPLE}18)`
            : 'rgba(0,212,255,0.03)',
          border: `2px dashed ${dragging ? CYAN : `${CYAN}33`}`,
          transition: 'all 0.3s',
          textAlign: 'center',
          flexShrink: 0,
        }}
      >
        <div style={{ fontSize: 40, color: CYAN, marginBottom: 8 }}>
          {importing ? (
            <Spin size="large" />
          ) : (
            <FolderOpenOutlined />
          )}
        </div>
        <p style={{ color: '#c8d0dc', fontSize: 15, fontWeight: 500, margin: '8px 0 4px' }}>
          {importing ? '正在导入…' : '拖拽视频文件到此处，或点击选择'}
        </p>
        <p style={{ color: '#4a5a7a', fontSize: 12, marginBottom: 16 }}>
          支持 MP4 / MOV / AVI / MKV / WMV
        </p>
        <Space size="middle">
          <Button
            icon={<FileOutlined />}
            onClick={(e) => { e.stopPropagation(); handleSelectFiles(); }}
            disabled={importing}
            style={{
              borderRadius: 8, borderColor: `${CYAN}44`, color: CYAN,
              background: 'transparent',
            }}
          >
            选择视频文件
          </Button>
          <Button
            icon={<FolderOpenOutlined />}
            onClick={(e) => { e.stopPropagation(); handleSelectFolder(); }}
            disabled={importing}
            style={{
              borderRadius: 8, borderColor: `${CYAN}44`, color: CYAN,
              background: 'transparent',
            }}
          >
            选择视频文件夹
          </Button>
        </Space>
      </div>

      {/* ─── 视频列表区域（可滚动） ─── */}
      {currentVideos.length > 0 && (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden' }}>
          {/* 视频列表标题栏 */}
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '4px 8px', marginBottom: 12, flexShrink: 0,
          }}>
            <Space>
              <Checkbox
                checked={allSelected}
                indeterminate={!allSelected && selectedEpisodeIds.length > 0}
                onChange={(e) => handleSelectAll(e.target.checked)}
                style={{ color: '#e0e6ed' }}
              >
                <span style={{ color: '#a0aec0', fontSize: 13 }}>
                  全选 ({selectedEpisodeIds.length}/{currentVideos.length})
                </span>
              </Checkbox>
            </Space>
            {importing && (
              <Space>
                <ReloadOutlined spin style={{ color: CYAN }} />
                <Text style={{ color: CYAN, fontSize: 12 }}>导入中...</Text>
              </Space>
            )}
            {!importing && (
              <Button
                type="text"
                size="small"
                icon={<ReloadOutlined spin={refreshing} />}
                onClick={handleRefresh}
                disabled={refreshing}
                style={{ color: refreshing ? CYAN : '#a0aec0', fontSize: 13 }}
              >
                {refreshing ? '刷新中…' : '刷新'}
              </Button>
            )}
          </div>

          {/* ─── 视频卡片列表（可滚动） ─── */}
          <div style={{ 
            display: 'flex', flexDirection: 'column', gap: 8, 
            flex: 1, 
            minHeight: 0,
            overflowY: 'auto',
            overflowX: 'hidden',
            paddingRight: 4,
          }}>
            {sortedVideos.map((video, idx) => {
              const selected = selectedEpisodeIds.includes(video.id);
              return (
                <div
                  key={video.id}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 12,
                    padding: '10px 16px', borderRadius: 12,
                    background: selected
                      ? `linear-gradient(135deg, ${CYAN}08, ${PURPLE}08)`
                      : 'rgba(255,255,255,0.02)',
                    border: selected
                      ? `1px solid ${CYAN}44`
                      : '1px solid rgba(255,255,255,0.05)',
                    cursor: 'pointer',
                    transition: 'all 0.2s',
                    flexShrink: 0,
                  }}
                >
                  {/* 复选框 */}
                  <Checkbox
                    checked={selected}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => handleSelect(video.id, e.target.checked)}
                    style={{ flexShrink: 0 }}
                  />

                  {/* 视频缩略图 */}
                  <div
                    onClick={(e) => { e.stopPropagation(); setPreviewVideo(video); }}
                    style={{ flexShrink: 0, position: 'relative' }}
                  >
                    <MiniPreview
                      filePath={video.path}
                      width={120}
                      height={68}
                    />
                    {/* 播放按钮叠加 */}
                    <div style={{
                      position: 'absolute', inset: 0,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      opacity: 0, transition: 'opacity 0.2s',
                      background: 'rgba(0,0,0,0.3)', borderRadius: 8,
                      cursor: 'pointer',
                    }}
                      className="mini-preview-overlay"
                      onMouseEnter={(e) => (e.currentTarget.style.opacity = '1')}
                      onMouseLeave={(e) => (e.currentTarget.style.opacity = '0')}
                    >
                      <PlayCircleOutlined style={{ fontSize: 24, color: '#fff' }} />
                    </div>
                  </div>

                  {/* 视频信息 */}
                  <div style={{ flex: 1, minWidth: 0 }} onClick={() => handleSelect(video.id, !selected)}>
                    <div style={{ fontWeight: 500, color: '#e0e6ed', fontSize: 14, marginBottom: 2 }}>
                      {video.name}
                    </div>
                    <Space split={<span style={{ color: '#2a3050' }}>·</span>}>
                      {(video.duration ?? 0) > 0 && (
                        <span style={{ color: '#4a5a7a', fontSize: 12 }}>
                          {formatDuration(video.duration ?? 0)}
                        </span>
                      )}
                      {(video.size ?? 0) > 0 && (
                        <span style={{ color: '#4a5a7a', fontSize: 12 }}>
                          {formatSize(video.size ?? 0)}
                        </span>
                      )}
                      {video.format && (
                        <span style={{ color: '#4a5a7a', fontSize: 12, textTransform: 'uppercase' }}>
                          {video.format}
                        </span>
                      )}
                    </Space>
                  </div>

                  {/* 预览按钮 */}
                  <Tooltip title="预览视频">
                    <Button
                      type="text"
                      size="small"
                      icon={<EyeOutlined />}
                      onClick={(e) => { e.stopPropagation(); setPreviewVideo(video); }}
                      style={{ color: '#4a5a7a', flexShrink: 0 }}
                    />
                  </Tooltip>
                </div>
              );
            })}
          </div>

          {/* ─── 底部操作（固定在底部） ─── */}
          <div style={{
            display: 'flex', justifyContent: 'center', gap: 16,
            padding: '16px 0',
            borderTop: '1px solid rgba(255,255,255,0.04)',
            flexShrink: 0,
            marginTop: 12,
          }}>
            <Button
              type="primary"
              size="large"
              onClick={handleStartAnalysis}
              disabled={selectedEpisodeIds.length === 0}
              icon={<PlayCircleOutlined />}
              style={{
                height: 48, borderRadius: 10, padding: '0 40px',
                background: `linear-gradient(135deg, ${CYAN}, ${PURPLE})`,
                border: 'none', fontWeight: 600, fontSize: 15, letterSpacing: 1,
                boxShadow: `0 0 24px ${CYAN}33`,
              }}
            >
              开始 AI 分析 ({selectedEpisodeIds.length} 个视频)
            </Button>
          </div>
        </div>
      )}

      {/* ─── 无视频时的空态 ─── */}
      {currentVideos.length === 0 && !importing && !refreshing && (
        <div style={{
          flex: 1,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: '#4a5a7a',
        }}>
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <span style={{ color: '#6b7b9d' }}>
                暂无视频，请拖拽或选择文件导入
              </span>
            }
          />
        </div>
      )}

      {/* ─── 导入中加载提示（无视频时） ─── */}
      {currentVideos.length === 0 && importing && (
        <div style={{
          flex: 1,
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          gap: 12, color: CYAN,
        }}>
          <Spin size="large" />
          <Text style={{ color: CYAN, fontSize: 14 }}>正在解析并导入视频资源，请稍候...</Text>
        </div>
      )}

      {/* ─── 刷新中加载提示（无视频时） ─── */}
      {currentVideos.length === 0 && refreshing && (
        <div style={{
          flex: 1,
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          gap: 12, color: CYAN,
        }}>
          <Spin size="large" />
          <Text style={{ color: CYAN, fontSize: 14 }}>正在重新扫描项目目录，请稍候...</Text>
        </div>
      )}

      {/* ─── 刷新中加载提示（已有视频时） ─── */}
      {refreshing && currentVideos.length > 0 && (
        <div style={{ textAlign: 'center', padding: 16, color: CYAN, flexShrink: 0 }}>
          <Spin size="small" style={{ marginRight: 8 }} />
          <Text style={{ color: CYAN }}>刷新视频列表中…</Text>
        </div>
      )}

      {/* ─── 视频预览模态框 ─── */}
      <VideoPlayerModal
        open={!!previewVideo}
        onClose={() => setPreviewVideo(null)}
        filePath={previewVideo?.path ?? ''}
        title={previewVideo?.name}
      />
    </div>
  );
};

export default ImportPanel;
