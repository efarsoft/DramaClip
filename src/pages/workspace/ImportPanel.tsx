/**
 * 导入视频面板 — 项目工作区 Step 1
 * 卡片式视频列表，支持多选和导入
 */

import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, message, Typography, Empty, Space, Checkbox, Card, Spin } from 'antd';
import {
  FolderOpenOutlined,
  UploadOutlined,
  PlayCircleOutlined,
  DeleteOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { useProjectStore } from '../../stores/projectStore';
import type { Episode } from '../../services/ipc';

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
    setImporting(true);
    try {
      const paths = Array.from(files).map((f: any) => f.path || f.name);
      await importVideos(currentProject.id, paths);
      message.success(`成功导入 ${paths.length} 个视频`);
    } catch (err: any) {
      message.error(err?.message || '导入失败');
    } finally {
      setImporting(false);
    }
  }, [currentProject, importVideos]);

  // 文件夹选择导入
  const handleOpenFolder = async () => {
    if (!currentProject) return;
    try {
      if (window.electronAPI?.dialog?.openFile) {
        const result = await window.electronAPI.dialog.openFile({
          properties: ['openFile', 'multiSelections'],
          filters: [{ name: '视频文件', extensions: ['mp4', 'mov', 'avi', 'mkv', 'wmv'] }],
        });
        if (result.success && result.data && result.data.length > 0) {
          setImporting(true);
          try {
            await importVideos(currentProject.id, result.data);
            message.success(`成功导入 ${result.data.length} 个视频`);
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

  // 开始分析（跳转到下一步）
  const handleStartAnalysis = () => {
    if (selectedEpisodeIds.length === 0) {
      message.warning('请至少选择一个视频进行分析');
      return;
    }
    if (!currentProject) return;
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

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: '32px 24px' }}>
      {/* ─── 标题 ─── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
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
          if (!importing) handleOpenFolder();
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
        <p style={{ color: '#4a5a7a', fontSize: 12, marginBottom: 12 }}>
          支持 MP4 / MOV / AVI / MKV / WMV
        </p>
        <Button
          icon={<FolderOpenOutlined />}
          onClick={(e) => { e.stopPropagation(); handleOpenFolder(); }}
          disabled={importing}
          style={{
            borderRadius: 8, borderColor: `${CYAN}44`, color: CYAN,
            background: 'transparent',
          }}
        >
          从文件夹选择
        </Button>
      </div>

      {/* ─── 视频列表标题栏 ─── */}
      {currentVideos.length > 0 && (
        <>
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '4px 8px', marginBottom: 12,
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

          {/* ─── 视频卡片列表 ─── */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 24 }}>
            {currentVideos.map((video, idx) => {
              const selected = selectedEpisodeIds.includes(video.id);
              return (
                <div
                  key={video.id}
                  onClick={() => handleSelect(video.id, !selected)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 12,
                    padding: '12px 16px', borderRadius: 12,
                    background: selected
                      ? `linear-gradient(135deg, ${CYAN}08, ${PURPLE}08)`
                      : 'rgba(255,255,255,0.02)',
                    border: selected
                      ? `1px solid ${CYAN}44`
                      : '1px solid rgba(255,255,255,0.05)',
                    cursor: 'pointer',
                    transition: 'all 0.2s',
                  }}
                >
                  {/* 复选框 */}
                  <Checkbox
                    checked={selected}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => handleSelect(video.id, e.target.checked)}
                    style={{ flexShrink: 0 }}
                  />

                  {/* 序号 */}
                  <span style={{
                    width: 24, height: 24, borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center',
                    background: 'rgba(255,255,255,0.06)', color: '#4a5a7a', fontSize: 11, fontWeight: 600,
                    fontFamily: "'JetBrains Mono', monospace", flexShrink: 0,
                  }}>
                    {idx + 1}
                  </span>

                  {/* 视频信息 */}
                  <div style={{ flex: 1, minWidth: 0 }}>
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

                  {/* 选中状态 */}
                  <div style={{
                    width: 20, height: 20, borderRadius: 6,
                    border: `2px solid ${selected ? CYAN : '#2a3050'}`,
                    background: selected ? CYAN : 'transparent',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    transition: 'all 0.2s', flexShrink: 0,
                  }}>
                    {selected && (
                      <svg viewBox="0 0 12 12" style={{ width: 10, height: 10 }}>
                        <path d="M2 6L5 9L10 3" stroke="#0a0e1a" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* ─── 底部操作 ─── */}
          <div style={{
            display: 'flex', justifyContent: 'center', gap: 16,
            padding: '16px 0',
            borderTop: '1px solid rgba(255,255,255,0.04)',
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
        </>
      )}

      {/* ─── 无视频时的空态 ─── */}
      {currentVideos.length === 0 && !importing && !refreshing && (
        <div style={{
          textAlign: 'center', padding: 48,
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

      {/* ─── 刷新中加载提示 ─── */}
      {refreshing && currentVideos.length > 0 && (
        <div style={{ textAlign: 'center', padding: 16, color: CYAN }}>
          <Spin size="small" style={{ marginRight: 8 }} />
          <Text style={{ color: CYAN }}>刷新视频列表中…</Text>
        </div>
      )}
    </div>
  );
};

export default ImportPanel;
