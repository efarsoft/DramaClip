/**
 * Central Model Catalog Tab — 中央模型目录（严格对齐 OmniVoice-Studio 理念）
 * 
 * 单一真相来源：models.yaml
 * 所有模型统一通过 huggingface_hub.snapshot_download 下载
 * 质量第一：不锁定任何引擎为默认
 * 
 * 展示 TTS / ASR / Diarization 全部条目 + 真实安装状态 + 一键下载 + 实时结构化进度
 */
import React, { useEffect, useState, useCallback } from 'react';
import { Card, Typography, Space, Button, Tag, Progress, message, Divider, Alert, Tooltip } from 'antd';
import {
  CheckCircleFilled,
  CloudDownloadOutlined,
  DeleteOutlined,
  InfoCircleOutlined,
  ExclamationCircleOutlined,
  LoadingOutlined,
  ExperimentOutlined,
} from '@ant-design/icons';
import { modelApi, ipcClient } from '../../services/ipc';

const { Title, Text, Paragraph } = Typography;

interface CentralCatalogEntry {
  repo_id: string;
  label: string;
  role: string;
  size_gb?: number;
  category?: string;
  note?: string;
  quality_notes?: string;
  installed?: boolean;
  size_on_disk_bytes?: number;
  download_supported?: boolean;
}

interface CentralModelsTabProps {
  modelDownloads: Record<string, { progress: number; message: string }>;
  onRefresh?: () => void;
}

export const CentralModelsTab: React.FC<CentralModelsTabProps> = ({
  modelDownloads,
  onRefresh,
}) => {
  const [catalog, setCatalog] = useState<CentralCatalogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [downloadingKeys, setDownloadingKeys] = useState<Record<string, boolean>>({});

  const loadCatalog = useCallback(async () => {
    setLoading(true);
    try {
      const res = await modelApi.list() as any;
      const central = (res && (res.central_catalog || res)) || [];
      // 兼容两种返回结构
      const list = Array.isArray(central) ? central : [];
      setCatalog(list);
    } catch (e) {
      message.error('加载中央模型目录失败');
      // 开发回退（展示最小集模型）
      setCatalog([
        { repo_id: 'iic/SenseVoiceSmall', label: 'SenseVoice Small (中文方言/情感/BGM)', role: 'ASR', size_gb: 0.9, note: '中文短剧首选 ASR' },
        { repo_id: 'hexgrad/Kokoro-82M-v1.1-zh', label: 'Kokoro-82M (中文)', role: 'TTS', size_gb: 0.15 },
      ]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadCatalog();
  }, [loadCatalog]);

  // 监听全局进度，实时更新下载中状态
  useEffect(() => {
    const unsub = ipcClient.onProgress((payload: any) => {
      if (payload?.task_id?.startsWith('model:') || payload?.phase === 'download') {
        // 触发轻量刷新（父组件会处理）
        if (onRefresh) onRefresh();
      }
    });
    return unsub;
  }, [onRefresh]);

  const handleDownload = async (repoId: string) => {
    setDownloadingKeys(prev => ({ ...prev, [repoId]: true }));
    try {
      const r = await modelApi.download(repoId);
      if (r?.success) {
        message.success(`开始下载 ${repoId}`);
      } else {
        message.warning(`模型 ${repoId} 已在下载或不可用`);
      }
    } catch (e: any) {
      message.error(`下载请求失败: ${e?.message || e}`);
    } finally {
      setTimeout(() => {
        setDownloadingKeys(prev => { const n = { ...prev }; delete n[repoId]; return n; });
        loadCatalog();
      }, 800);
    }
  };

  const handleDelete = async (repoId: string, label: string) => {
    try {
      await modelApi.delete(repoId);
      message.success(`已删除 ${label}`);
      loadCatalog();
    } catch (e) {
      message.error('删除失败');
    }
  };

  const getRoleColor = (role: string) => {
    const r = (role || '').toLowerCase();
    if (r.includes('tts')) return 'cyan';
    if (r.includes('asr') || r.includes('whisper') || r.includes('sense')) return 'purple';
    if (r.includes('diar')) return 'orange';
    return 'default';
  };

  const formatSize = (gb?: number) => {
    if (!gb) return '未知';
    return gb >= 1 ? `${gb.toFixed(1)} GB` : `${(gb * 1024).toFixed(0)} MB`;
  };

  const grouped = React.useMemo(() => {
    const groups: Record<string, CentralCatalogEntry[]> = { TTS: [], ASR: [], Diarisation: [], Other: [] };
    for (const m of catalog) {
      const role = (m.role || m.category || 'Other').toString();
      if (role.toUpperCase().includes('TTS')) groups.TTS.push(m);
      else if (role.toUpperCase().includes('ASR') || role.toUpperCase().includes('WHISPER') || role.includes('Sense')) groups.ASR.push(m);
      else if (role.toLowerCase().includes('diar')) groups.Diarisation.push(m);
      else groups.Other.push(m);
    }
    return groups;
  }, [catalog]);

  const renderModelCard = (m: CentralCatalogEntry) => {
    const key = m.repo_id;
    const dlInfo = modelDownloads[`model:${key}`] || modelDownloads[key];
    const isDownloading = !!downloadingKeys[key] || (dlInfo && dlInfo.progress >= 0 && dlInfo.progress < 100);
    const progress = dlInfo ? Math.max(0, Math.min(100, dlInfo.progress || 0)) : 0;
    const installed = !!m.installed;

    return (
      <Card
        key={key}
        style={{
          background: 'rgba(24,24,37,0.72)',
          borderRadius: 12,
          border: installed ? '1px solid rgba(16,185,129,0.35)' : '1px solid rgba(255,255,255,0.08)',
          marginBottom: 12,
        }}
        styles={{ body: { padding: 16 } }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
          <div style={{ flex: 1 }}>
            <Space size={8} style={{ marginBottom: 6 }}>
              <Text strong style={{ fontSize: 15, color: '#f4f4f5' }}>{m.label || m.repo_id}</Text>
              <Tag color={getRoleColor(m.role)} style={{ borderRadius: 4 }}>{m.role}</Tag>
              {installed && (
                <Tag icon={<CheckCircleFilled />} color="success" style={{ borderRadius: 4 }}>已安装</Tag>
              )}
            </Space>

            <div style={{ fontFamily: 'monospace', fontSize: 12, color: '#71717a', marginBottom: 8 }}>
              {m.repo_id}
            </div>

            {(m.quality_notes || m.note) && (
              <Paragraph style={{ color: '#a1a1aa', fontSize: 13, marginBottom: 8 }} ellipsis={{ rows: 2 }}>
                {m.quality_notes || m.note}
              </Paragraph>
            )}

            <div style={{ color: '#71717a', fontSize: 12 }}>
              预估大小：{formatSize(m.size_gb)}
              {m.size_on_disk_bytes ? `  ·  已占用 ${(m.size_on_disk_bytes / 1024 / 1024).toFixed(0)} MB` : ''}
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8, minWidth: 140 }}>
            {isDownloading ? (
              <div style={{ width: '100%' }}>
                <Progress
                  percent={progress}
                  size="small"
                  status="active"
                  strokeColor={{ '0%': '#3b82f6', '100%': '#6366f1' }}
                  format={() => <span style={{ color: '#e4e4e7', fontSize: 12 }}>{dlInfo?.message || `${progress}%`}</span>}
                />
              </div>
            ) : null}

            {installed ? (
              <Button
                danger
                ghost
                size="small"
                icon={<DeleteOutlined />}
                onClick={() => handleDelete(key, m.label || key)}
              >
                删除
              </Button>
            ) : (
              <Button
                type="primary"
                size="small"
                icon={<CloudDownloadOutlined />}
                loading={isDownloading}
                disabled={isDownloading}
                onClick={() => handleDownload(key)}
                style={{ background: 'linear-gradient(135deg, #4f46e5 0%, #3b82f6 100%)', border: 'none' }}
              >
                一键下载
              </Button>
            )}
          </div>
        </div>
      </Card>
    );
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div>
          <Title level={5} style={{ margin: 0, color: '#f4f4f5' }}>中央模型目录</Title>
          <Text type="secondary" style={{ fontSize: 12 }}>
            单一真相来源 · 全部走 huggingface_hub.snapshot_download · 质量优先（不锁定默认）
          </Text>
        </div>
        <Button size="small" onClick={loadCatalog} loading={loading}>刷新状态</Button>
      </div>

      <Alert
        style={{ marginBottom: 16 }}
        type="info"
        showIcon
        icon={<ExperimentOutlined />}
        message="安装完成即可用"
        description="下载任意本地模型后，对应 TTS / ASR 引擎会立即可用。推荐先下载 SenseVoiceSmall（ASR）验证流程，默认 TTS 使用 edge_tts (云端)。说话人分离默认使用内置聚类算法，无需额外模型。"
      />

      {/* P8 快速开始推荐包 */}
      <div style={{ marginBottom: 12 }}>
        <Typography.Text strong style={{ fontSize: 13 }}>推荐快速开始包（轻量高质）</Typography.Text>
        <div style={{ marginTop: 6 }}>
          <Button
            size="small"
            onClick={async () => {
              const kokoro = catalog.find(c => c.repo_id.includes('Kokoro'));
              if (kokoro && !kokoro.installed) await handleDownload(kokoro.repo_id);
              message.success('正在下载 Kokoro 轻量中文 TTS（最快验证路径）');
            }}
            style={{ marginRight: 8 }}
          >
            一键安装 Kokoro（轻量中文 TTS）
          </Button>
          <Button
            size="small"
            onClick={async () => {
              const sense = catalog.find(c => c.repo_id.includes('SenseVoice'));
              if (sense && !sense.installed) await handleDownload(sense.repo_id);
            }}
          >
            一键安装 SenseVoice（强中文方言/情绪 ASR）
          </Button>
        </div>
      </div>

      {loading && catalog.length === 0 ? (
        <div style={{ padding: 40, textAlign: 'center', color: '#71717a' }}>正在加载中央目录...</div>
      ) : (
        <>
          {grouped.TTS.length > 0 && (
            <>
              <div style={{ color: '#818cf8', fontWeight: 600, margin: '12px 0 8px' }}>TTS · 高质量语音合成</div>
              {grouped.TTS.map(renderModelCard)}
            </>
          )}
          {grouped.ASR.length > 0 && (
            <>
              <Divider style={{ borderColor: 'rgba(255,255,255,0.06)', margin: '16px 0 8px' }} />
              <div style={{ color: '#c026ff', fontWeight: 600, margin: '12px 0 8px' }}>ASR · 语音识别（含方言/情绪）</div>
              {grouped.ASR.map(renderModelCard)}
            </>
          )}
          {grouped.Diarisation && grouped.Diarisation.length > 0 && (
            <>
              <Divider style={{ borderColor: 'rgba(255,255,255,0.06)', margin: '16px 0 8px' }} />
              <div style={{ color: '#f59e0b', fontWeight: 600, margin: '12px 0 8px' }}>Diarization · 说话人分离（精准模式）</div>
              {grouped.Diarisation.map(renderModelCard)}
            </>
          )}
          {grouped.Other.length > 0 && grouped.Other.map(renderModelCard)}
        </>
      )}

      <div style={{ marginTop: 16, fontSize: 12, color: '#71717a' }}>
        提示：下载使用标准 HF 断点续传。说话人分离默认使用内置聚类算法，无需下载额外模型。
      </div>
    </div>
  );
};

export default CentralModelsTab;
