/**
 * Phase 4: 首次使用智能引导 - 推荐高质量本地引擎套装
 * 让新用户能一键获得接近「安装完成即用」的体验
 */
import React, { useEffect, useState } from 'react';
import { Modal, Button, Card, Radio, Space, Typography, Progress, message, Tag } from 'antd';
import { RocketOutlined, CheckCircleOutlined, LoadingOutlined, DatabaseOutlined } from '@ant-design/icons';
import { systemApi, ipcClient } from '../../services/ipc';
import { detectRecommendedPack } from '../../utils/hardware';
import { useNavigate } from 'react-router-dom';

const { Title, Text, Paragraph } = Typography;

interface Pack {
  id: string;
  name: string;
  description: string;
  estimated_size_gb: number;
  recommended_for: string;
}

interface OnboardingModalProps {
  open: boolean;
  onClose: () => void;
  onComplete: () => void;
}

export const OnboardingModal: React.FC<OnboardingModalProps> = ({ open, onClose, onComplete }) => {
  const navigate = useNavigate();
  const [packs, setPacks] = useState<Pack[]>([]);
  const [recommendedId, setRecommendedId] = useState<string>('light_high_quality');
  const [selectedPack, setSelectedPack] = useState<string>('light_high_quality');
  const [installing, setInstalling] = useState(false);
  const [installProgress, setInstallProgress] = useState(0);
  const [installMessage, setInstallMessage] = useState('');
  const [liveTaskId, setLiveTaskId] = useState<string | null>(null);
  const [installError, setInstallError] = useState<string | null>(null);
  const [installSuccess, setInstallSuccess] = useState(false);

  useEffect(() => {
    if (open) {
      loadRecommendations();
    }
  }, [open]);

  // Phase 4: 实时监听安装进度（对接全局 progress 系统）
  useEffect(() => {
    if (!liveTaskId) return;

    const unsub = ipcClient.onProgress((payload: any) => {
      if (payload?.task_id === liveTaskId || payload?.task_id?.includes('cosyvoice')) {
        const pct = typeof payload.progress === 'number' ? payload.progress : (payload.pct || 0);
        setInstallProgress(Math.max(0, Math.min(100, pct)));
        if (payload.message || payload.phase) {
          setInstallMessage(payload.message || payload.phase || '安装中...');
        }
        if (pct >= 100 || payload.phase === 'done' || payload.phase === 'completed') {
          setTimeout(() => {
            setLiveTaskId(null);
          }, 600);
        }
      }
    });

    return unsub;
  }, [liveTaskId]);

  const loadRecommendations = async () => {
    try {
      const res = await systemApi.getOnboardingRecommendations();
      if (res.packs) setPacks(res.packs);

      // 结合后端推荐 + 前端硬件检测
      const backendRecommended = res.recommended_pack_id || 'light_high_quality';
      const frontendRecommended = await detectRecommendedPack();

      const finalRecommended = frontendRecommended === 'extreme_quality' ? frontendRecommended : backendRecommended;

      setRecommendedId(finalRecommended);
      setSelectedPack(finalRecommended);
    } catch (e) {
      setPacks([
        { id: 'light_high_quality', name: '轻量高质套装', description: 'Kokoro + SenseVoice', estimated_size_gb: 1.1, recommended_for: '大多数用户' },
        { id: 'extreme_quality', name: '极致成片套装', description: 'CosyVoice3 + pyannote', estimated_size_gb: 3.0, recommended_for: '追求最高质量' },
      ]);
      setRecommendedId('light_high_quality');
      setSelectedPack('light_high_quality');
    }
  };

  const handleInstall = async () => {
    setInstalling(true);
    setInstallProgress(5);
    setInstallMessage('正在准备安装...');

    try {
      // 1. 先应用配置（切换引擎等）
      await systemApi.applyOnboardingPack(selectedPack);

      if (selectedPack === 'extreme_quality') {
        // 启动真实安装，并监听进度
        setLiveTaskId('cosyvoice:install_runtime');
        setInstallMessage('正在安装 CosyVoice 隔离运行时（这可能需要几分钟）...');

        const res = await (window as any).electron?.ipcRenderer?.invoke?.('cosyvoice:installRuntime');

        setLiveTaskId(null);

        if (!res?.success) {
          throw new Error(res?.message || '安装失败');
        }
      } else {
        // 轻量套装：配置已切换，后续模型可通过中央目录下载
        setInstallProgress(80);
        setInstallMessage('轻量套装配置已应用');
        await new Promise(r => setTimeout(r, 400));
      }

      setInstallProgress(100);
      setInstallMessage('安装完成！');
      setInstallSuccess(true);
      setInstalling(false);

      setTimeout(() => {
        message.success('推荐套装已应用，高质量本地引擎已就绪！');
        onComplete();
        onClose();
      }, 1200);
    } catch (err: any) {
      const errMsg = err.message || String(err);
      setInstallError(errMsg);
      message.error(`安装失败: ${errMsg}`);
      setInstalling(false);
      setLiveTaskId(null);
    }
  };

  const handleRetry = () => {
    setInstallError(null);
    setInstallProgress(0);
    setInstallMessage('');
    handleInstall();
  };

  return (
    <Modal
      title={<Title level={4}><RocketOutlined /> 欢迎使用 DramaClip - 推荐高质量本地引擎</Title>}
      open={open}
      onCancel={onClose}
      footer={null}
      width={720}
      destroyOnHidden
    >
      <Paragraph>
        为了获得最佳成片效果，我们推荐你安装以下高质量本地模型套装。
        安装后即可实现接近“安装完成即用”的体验。
      </Paragraph>

      <Radio.Group
        value={selectedPack}
        onChange={(e) => setSelectedPack(e.target.value)}
        style={{ width: '100%' }}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          {packs.map((pack) => (
            <Card
              key={pack.id}
              hoverable
              style={{
                border: selectedPack === pack.id ? '2px solid #1677ff' : undefined,
                marginBottom: 12,
              }}
            >
              <Radio value={pack.id} style={{ width: '100%' }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 16 }}>
                    {pack.name}
                    {pack.id === recommendedId && <Tag color="blue" style={{ marginLeft: 8 }}>推荐</Tag>}
                  </div>
                  <div style={{ color: '#666', margin: '4px 0' }}>{pack.description}</div>
                  <div style={{ fontSize: 12, color: '#888' }}>
                    预计大小：{pack.estimated_size_gb} GB · {pack.recommended_for}
                  </div>
                </div>
              </Radio>
            </Card>
          ))}
        </Space>
      </Radio.Group>

      {installSuccess && (
        <div style={{ marginTop: 24, padding: 16, background: '#f6ffed', border: '1px solid #b7eb8f', borderRadius: 8 }}>
          <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 8 }} />
          <Text strong style={{ color: '#389e0d' }}>安装成功！高质量本地引擎已就绪。</Text>
        </div>
      )}

      {installError && (
        <div style={{ marginTop: 24, padding: 16, background: '#fff2e8', border: '1px solid #ffbb96', borderRadius: 8 }}>
          <Text type="danger">安装失败：{installError}</Text>
          <div style={{ marginTop: 12 }}>
            <Button type="primary" danger size="small" onClick={handleRetry}>
              重试安装
            </Button>
            <Button size="small" style={{ marginLeft: 8 }} onClick={() => { setInstallError(null); onClose(); }}>
              稍后手动安装
            </Button>
          </div>
        </div>
      )}

      {!installSuccess && !installError && (
        <>
          {installing && (
            <div style={{ marginTop: 24 }}>
              <Progress 
                percent={installProgress} 
                status="active" 
                strokeColor={{ from: '#1677ff', to: '#52c41a' }}
              />
              <div style={{ marginTop: 8, color: '#666', fontSize: 13 }}>{installMessage}</div>
            </div>
          )}

          <div style={{ marginTop: 24, textAlign: 'right' }}>
            <Button onClick={onClose} style={{ marginRight: 12 }} disabled={installing}>
              稍后再说
            </Button>
            <Button
              type="primary"
              icon={<DatabaseOutlined />}
              onClick={() => navigate('/models')}
            >
              前往模型管理进行安装
            </Button>
          </div>
        </>
      )}

      <div style={{ marginTop: 16, fontSize: 12, color: '#999' }}>
        提示：强烈建议前往独立的「模型管理」页面进行下载和安装，体验更好。
      </div>
    </Modal>
  );
};

export default OnboardingModal;
