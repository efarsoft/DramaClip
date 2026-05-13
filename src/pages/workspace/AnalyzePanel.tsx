/**
 * AI 分析面板 — 项目工作区 Step 2
 * 从 AnalyzePage 提取，精华为工作区步骤组件
 */

import React, { useEffect, useRef, useState } from 'react';
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
} from 'antd';
import {
  PlayCircleOutlined,
  StopOutlined,
  CheckCircleFilled,
} from '@ant-design/icons';
import { analyzeApi, type AnalysisStatus } from '../../services/ipc';
import { useProjectStore } from '../../stores/projectStore';
import { EmotionCurve } from '../../components/chart/EmotionCurve';

const { Title, Text } = Typography;
const CYAN = '#00d4ff';

// ─── Mock 数据 ───
const MOCK_ASR = [
  { start: 0.0, end: 3.5, text: '这是一个测试台词。', speaker: '角色1' },
  { start: 4.0, end: 8.2, text: '这是第二段对话内容。', speaker: '角色2' },
  { start: 9.5, end: 15.0, text: '这里包含更多对话内容用于演示。', speaker: '角色1' },
];
const MOCK_EMOTION = [
  { timestamp: 0, emotion: 'neutral', intensity: 0.3 },
  { timestamp: 3, emotion: 'joy', intensity: 0.7 },
  { timestamp: 6, emotion: 'anger', intensity: 0.5 },
  { timestamp: 9, emotion: 'surprise', intensity: 0.8 },
  { timestamp: 12, emotion: 'joy', intensity: 0.6 },
];

const PHASE_LABELS: Record<string, string> = {
  asr: '语音识别',
  emotion: '情绪分析',
  highlight: '高光识别',
  completed: '分析完成',
  failed: '分析失败',
  idle: '准备就绪',
};

interface Props {
  onNext: () => void;
}

const AnalyzePanel: React.FC<Props> = ({ onNext }) => {
  const { currentProject } = useProjectStore();

  const [analyzing, setAnalyzing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [phase, setPhase] = useState('idle');
  const [error, setError] = useState<string | null>(null);
  const [asrResults, setAsrResults] = useState<typeof MOCK_ASR>([]);
  const [emotionData, setEmotionData] = useState<typeof MOCK_EMOTION>([]);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const startPolling = (taskId: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const status: AnalysisStatus | null = await analyzeApi.getStatus(taskId);
        if (!status) return;
        const done = ['completed', 'failed', 'cancelled'].includes(status.status);
        setProgress(status.progress ?? 0);
        setPhase(status.phase ?? 'idle');
        if (done) {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          if (status.status === 'completed') {
            setAnalyzing(false);
            setAsrResults(MOCK_ASR);
            setEmotionData(MOCK_EMOTION);
            setPhase('completed');
          } else {
            setAnalyzing(false);
            setError(status.message ?? '分析失败');
          }
        }
      } catch { /* 网络抖动忽略 */ }
    }, 1000);
  };

  const handleStart = async () => {
    if (!currentProject) return;
    setError(null);
    setAsrResults([]);
    setEmotionData([]);
    setProgress(0);
    try {
      const { task_id } = await analyzeApi.start(currentProject.id, []);
      setAnalyzing(true);
      startPolling(task_id);
    } catch (err: any) {
      setError(err?.message || '启动失败');
    }
  };

  const handleCancel = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    setAnalyzing(false);
    setPhase('idle');
    setProgress(0);
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
          {analyzing ? (
            <Button danger icon={<StopOutlined />} onClick={handleCancel} style={{ borderRadius: 8, height: 40 }}>
              取消分析
            </Button>
          ) : phase !== 'completed' ? (
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              onClick={handleStart}
              style={{
                height: 40, borderRadius: 8, padding: '0 24px',
                background: `linear-gradient(135deg, ${CYAN}, #7c3aed)`,
                border: 'none', fontWeight: 600,
                boxShadow: `0 0 20px ${CYAN}33`,
              }}
            >
              开始分析
            </Button>
          ) : (
            <Button
              type="primary"
              onClick={onNext}
              size="large"
              style={{
                height: 40, borderRadius: 8, padding: '0 24px',
                background: '#10b981', border: 'none', fontWeight: 600,
              }}
            >
              查看方案 <CheckCircleFilled style={{ marginLeft: 6 }} />
            </Button>
          )}
        </Space>
      </div>

      {/* ─── 进度 ─── */}
      {analyzing && (
        <Card style={{ marginBottom: 16, background: 'rgba(0,212,255,0.03)', borderColor: `${CYAN}22`, borderRadius: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <Spin size="small" style={{ color: CYAN }} />
            <div style={{ flex: 1 }}>
              <Text strong style={{ color: '#e0e6ed' }}>{PHASE_LABELS[phase] || '处理中'}</Text>
            </div>
            <Text style={{ color: CYAN, fontFamily: "'JetBrains Mono', monospace" }}>{progress}%</Text>
          </div>
          <Progress percent={progress} strokeColor={{ '0%': '#108ee9', '100%': '#87d068' }} style={{ marginTop: 8, borderRadius: 4 }} />
        </Card>
      )}

      {/* ─── 错误 ─── */}
      {error && <Alert message={error} type="error" showIcon closable style={{ marginBottom: 16, borderRadius: 8 }} onClose={() => setError(null)} />}

      {/* ─── ASR 结果 ─── */}
      {asrResults.length > 0 && (
        <Card style={{ marginBottom: 16, background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.06)', borderRadius: 12 }} title={<span style={{ color: '#e0e6ed' }}>📝 语音识别结果</span>}>
          <Table
            dataSource={asrResults}
            size="small"
            bordered
            rowKey={(_, i) => i ?? 0}
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

      {/* ─── 情绪曲线 ─── */}
      {emotionData.length > 0 && (
        <Card style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.06)', borderRadius: 12 }} title={<span style={{ color: '#e0e6ed' }}>📊 情绪曲线</span>}>
          <EmotionCurve data={emotionData} height={200} />
        </Card>
      )}
    </div>
  );
};

export default AnalyzePanel;
