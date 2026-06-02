/**
 * Phase 4: 高质量引擎健康面板
 * 让用户一目了然看到哪些顶级本地引擎已就绪，并能一键修复
 */
import React, { useEffect, useState } from 'react';
import { Card, Button, Tag, Space, Typography, Progress, message } from 'antd';
import { CheckCircleOutlined, WarningOutlined, SyncOutlined, ExperimentOutlined } from '@ant-design/icons';
import { systemApi, modelApi } from '../../services/ipc';

const { Text } = Typography;

interface EngineStatus {
  id: string;
  name: string;
  available: boolean;
  isolation_mode?: string;
  reason?: string;
  category?: string;
  repo_id?: string;
}

export const QualityEnginesPanel: React.FC = () => {
  const [engines, setEngines] = useState<EngineStatus[]>([]);
  const [loading, setLoading] = useState(false);
  const [installingId, setInstallingId] = useState<string | null>(null);

  const loadEngines = async () => {
    setLoading(true);
    try {
      const [ttsList, modelRes] = await Promise.all([
        systemApi.ttsBackends(),
        modelApi.list().catch(() => ({ central_catalog: [] })) as any,
      ]);

      const engines: EngineStatus[] = [];

      // 1. 高质量 TTS
      const ttsPriority = ['cosyvoice_subprocess', 'cosyvoice', 'kokoro'];
      ttsList
        .filter((b: any) => ttsPriority.includes(b.id))
        .sort((a: any, b: any) => ttsPriority.indexOf(a.id) - ttsPriority.indexOf(b.id))
        .forEach((b: any) => {
          engines.push({
            id: b.id,
            name: b.display_name || b.id,
            available: b.available,
            isolation_mode: b.isolation_mode,
            reason: b.reason,
            category: 'tts',
          });
        });

      // 2. 高质量 ASR + Diarization from central catalog
      const central = modelRes.central_catalog || modelRes || [];
      const highQualityRepos = [
        'iic/SenseVoiceSmall',
        'hexgrad/Kokoro-82M-v1.1-zh',
      ];

      central
        .filter((m: any) => highQualityRepos.includes(m.repo_id))
        .forEach((m: any) => {
          const isInstalled = m.installed;
          engines.push({
            id: m.repo_id,
            name: m.label || m.repo_id,
            available: isInstalled,
            reason: isInstalled ? undefined : '未下载',
            category: m.role === 'ASR' ? 'asr' : 'diarization',
            repo_id: m.repo_id,
          });
        });

      setEngines(engines);
    } catch (e) {
      // 降级数据
      setEngines([
        { id: 'cosyvoice_subprocess', name: 'CosyVoice 3 (进程隔离)', available: false, reason: '需安装运行时', category: 'tts' },
        { id: 'kokoro', name: 'Kokoro-82M', available: true, category: 'tts' },
        { id: 'iic/SenseVoiceSmall', name: 'SenseVoice Small', available: false, reason: '未下载', category: 'asr', repo_id: 'iic/SenseVoiceSmall' },
      ]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadEngines();
  }, []);

  const handleInstall = async (engine: EngineStatus) => {
    const engineId = engine.id;

    if (engineId === 'cosyvoice_subprocess') {
      setInstallingId(engineId);
      try {
        const res = await (window as any).electron?.ipcRenderer?.invoke?.('cosyvoice:installRuntime');
        if (res?.success) {
          message.success('CosyVoice 隔离运行时安装成功！');
          await loadEngines();
        } else {
          message.error(res?.message || '安装失败');
        }
      } catch (e) {
        message.error('安装调用失败');
      } finally {
        setInstallingId(null);
      }
      return;
    }

    // ASR / Diarization → 使用中央模型下载
    if (engine.repo_id) {
      setInstallingId(engineId);
      try {
        await modelApi.download(engine.repo_id);
        message.success(`${engine.name} 下载已启动，请在模型管理中查看进度`);
        // 延迟刷新
        setTimeout(() => loadEngines(), 1500);
      } catch (e) {
        message.error('下载启动失败，请前往模型管理手动操作');
      } finally {
        setInstallingId(null);
      }
    } else {
      message.info('请前往「模型管理」标签页下载对应模型');
    }
  };

  return (
    <Card
      title="高质量本地引擎状态"
      extra={<Button size="small" onClick={loadEngines} loading={loading} icon={<SyncOutlined />}>刷新</Button>}
      style={{ marginBottom: 16 }}
    >
      <Space direction="vertical" style={{ width: '100%' }}>
        {engines.map((eng) => (
          <div key={eng.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: '1px solid #f0f0f0' }}>
            <div>
              <Text strong>{eng.name || eng.id}</Text>
              {eng.isolation_mode === 'subprocess' && <Tag color="purple" style={{ marginLeft: 8 }}>隔离模式</Tag>}
              {eng.category === 'asr' && <Tag color="cyan" style={{ marginLeft: 8 }}>ASR</Tag>}
              {eng.category === 'diarization' && <Tag color="orange" style={{ marginLeft: 8 }}>Diarization</Tag>}
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              {eng.available ? (
                <Tag icon={<CheckCircleOutlined />} color="success">已就绪</Tag>
              ) : (
                <Tag icon={<WarningOutlined />} color="warning">未就绪</Tag>
              )}

              {!eng.available && (
                <Button
                  size="small"
                  type="primary"
                  loading={installingId === eng.id}
                  onClick={() => handleInstall(eng)}
                  icon={eng.category === 'diarization' ? <ExperimentOutlined /> : undefined}
                >
                  一键安装/修复
                </Button>
              )}
            </div>
          </div>
        ))}
      </Space>

      <div style={{ marginTop: 12, fontSize: 12, color: '#888' }}>
        提示：安装隔离运行时后，高品质中文TTS即可稳定使用。ASR 与说话人分离引擎请前往「模型管理」一键下载。
        <Button size="small" type="link" style={{ padding: 0, marginLeft: 8 }} onClick={() => window.location.hash = '#settings-central-models'}>
          前往模型管理
        </Button>
      </div>
    </Card>
  );
};
