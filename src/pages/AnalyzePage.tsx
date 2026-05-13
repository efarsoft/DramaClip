/**
 * 视频分析页面（简化版）
 * MUI → antd 迁移
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
  ReloadOutlined,
} from '@ant-design/icons';
import { analyzeApi, type AnalysisStatus } from '../services/ipc';
import { useProjectStore } from '../stores/projectStore';
import { EmotionCurve } from '../components/chart/EmotionCurve';

const { Title, Text } = Typography;

// ─── Mock 数据（占位，直到后端提供真实结果） ───────────────────────
const MOCK_ASR_RESULTS = [
  { start: 0.0, end: 3.5, text: '这是一个测试台词。', speaker: '角色1' },
  { start: 4.0, end: 8.2, text: '这是第二段对话内容。', speaker: '角色2' },
  { start: 9.5, end: 15.0, text: '这里包含更多对话内容用于演示。', speaker: '角色1' },
];

const MOCK_EMOTION_DATA = [
  { timestamp: 0, emotion: 'neutral', intensity: 0.3 },
  { timestamp: 3, emotion: 'joy', intensity: 0.7 },
  { timestamp: 6, emotion: 'anger', intensity: 0.5 },
  { timestamp: 9, emotion: 'surprise', intensity: 0.8 },
  { timestamp: 12, emotion: 'joy', intensity: 0.6 },
];

// ─── 阶段标签映射 ────────────────────────────────────────────────────
const PHASE_LABELS: Record<string, string> = {
  asr: '语音识别中',
  emotion: '情绪分析中',
  highlight: '高光识别中',
  completed: '分析完成',
  failed: '分析失败',
  idle: '准备中',
};

// ─── 本地状态 ────────────────────────────────────────────────────────
interface LocalState {
  isAnalyzing: boolean;
  progress: number;
  phase: string;
  message: string;
  asrResults: typeof MOCK_ASR_RESULTS;
  emotionData: typeof MOCK_EMOTION_DATA;
  error: string | null;
}

export const AnalyzePage: React.FC = () => {
  const { currentProject, currentVideos } = useProjectStore();

  const [state, setState] = useState<LocalState>({
    isAnalyzing: false,
    progress: 0,
    phase: 'idle',
    message: '',
    asrResults: [],
    emotionData: [],
    error: null,
  });

  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ─── 清理轮询（组件卸载时） ──────────────────────────────────────────
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };
  }, []);

  // ─── 启动轮询 ────────────────────────────────────────────────────────
  const startPolling = (taskId: string) => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
    }
    pollIntervalRef.current = setInterval(async () => {
      try {
        const status: AnalysisStatus | null = await analyzeApi.getStatus(taskId);
        if (!status) return;

        const done = status.status === 'completed' || status.status === 'failed' || status.status === 'cancelled';

        setState((prev) => ({
          ...prev,
          progress: status.progress ?? prev.progress,
          phase: status.phase ?? prev.phase,
          message: status.message ?? prev.message,
          isAnalyzing: !done,
        }));

        if (done) {
          if (pollIntervalRef.current) {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;
          }

          if (status.status === 'completed') {
            setState((prev) => ({
              ...prev,
              isAnalyzing: false,
              asrResults: MOCK_ASR_RESULTS,
              emotionData: MOCK_EMOTION_DATA,
              phase: 'completed',
              message: '分析完成',
            }));
          } else {
            setState((prev) => ({
              ...prev,
              isAnalyzing: false,
              error: status.message ?? '分析已取消或失败',
            }));
          }
        }
      } catch {
        // 轮询出错继续（可能是网络抖动）
      }
    }, 1000);
  };

  // ─── 开始分析 ────────────────────────────────────────────────────────
  const handleStartAnalysis = async () => {
    if (!currentProject) return;

    setState((prev) => ({ ...prev, error: null, asrResults: [], emotionData: [] }));

    try {
      // 获取项目中的第一个视频路径（如果有）
      const firstVideo = currentVideos && currentVideos.length > 0 ? currentVideos[0].path : '';
      const { task_id } = await analyzeApi.start(currentProject.id, firstVideo ? [firstVideo] : []);
      startPolling(task_id);
    } catch (err) {
      setState((prev) => ({
        ...prev,
        error: err instanceof Error ? err.message : '分析启动失败',
      }));
    }
  };

  // ─── 取消分析 ────────────────────────────────────────────────────────
  const handleCancelAnalysis = async () => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    try {
      // TODO: 调用 analyzeApi.cancel(taskId) 取消后端任务
      setState((prev) => ({ ...prev, isAnalyzing: false, phase: 'idle', message: '已取消' }));
    } catch (err) {
      setState((prev) => ({
        ...prev,
        error: err instanceof Error ? err.message : '取消失败',
      }));
    }
  };

  // ─── 重置 ────────────────────────────────────────────────────────────
  const handleReset = () => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    setState({
      isAnalyzing: false,
      progress: 0,
      phase: 'idle',
      message: '',
      asrResults: [],
      emotionData: [],
      error: null,
    });
  };

  // ─── 无项目提示 ──────────────────────────────────────────────────────
  if (!currentProject) {
    return (
      <div style={{ padding: '24px', textAlign: 'center' }}>
        <Empty
          description="请先打开一个项目"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      </div>
    );
  }

  return (
    <div style={{ padding: '24px' }}>
      {/* 项目信息 + 操作栏 */}
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Title level={2} style={{ margin: 0 }}>
          视频分析
          <Text type="secondary" style={{ fontSize: 14, marginLeft: 12 }}>
            {currentProject.name}
          </Text>
        </Title>
        <Space>
          {state.isAnalyzing ? (
            <Button
              danger
              icon={<StopOutlined />}
              onClick={handleCancelAnalysis}
            >
              取消分析
            </Button>
          ) : (
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              onClick={handleStartAnalysis}
              disabled={!currentProject}
            >
              开始分析
            </Button>
          )}
          {state.asrResults.length > 0 && (
            <Button icon={<ReloadOutlined />} onClick={handleReset}>
              重置
            </Button>
          )}
        </Space>
      </div>

      {/* 分析进度条 */}
      {state.isAnalyzing && (
        <Card style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <Spin size="small" />
            <div style={{ flex: 1 }}>
              <Title level={5} style={{ margin: '0 0 4px 0' }}>
                {PHASE_LABELS[state.phase] || PHASE_LABELS.idle}
              </Title>
              <Text type="secondary">{state.message || '准备中...'}</Text>
            </div>
            <Text strong>{state.progress}%</Text>
          </div>
          <Progress
            percent={state.progress}
            strokeColor={{ '0%': '#108ee9', '100%': '#87d068' }}
            style={{ borderRadius: 4, marginTop: 8 }}
          />
        </Card>
      )}

      {/* 错误提示 */}
      {state.error && (
        <Alert
          message={state.error}
          type="error"
          showIcon
          closable
          style={{ marginBottom: 16 }}
          onClose={() => setState((prev) => ({ ...prev, error: null }))}
        />
      )}

      {/* 分析完成但未获取到结果 */}
      {!state.isAnalyzing
        && !state.error
        && state.asrResults.length === 0
        && state.phase !== 'idle' && (
        <Alert
          message="分析完成，但未获取到结果"
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          action={
            <Button size="small" onClick={handleStartAnalysis}>
              重新分析
            </Button>
          }
        />
      )}

      {/* ASR 识别结果表格 */}
      {state.asrResults.length > 0 && (
        <Card style={{ marginBottom: 16 }} title="语音识别结果">
          <Table
            dataSource={state.asrResults}
            size="small"
            bordered
            rowKey={(_, index) => index ?? 0}
            pagination={false}
            columns={[
              {
                title: '开始时间',
                dataIndex: 'start',
                key: 'start',
                width: 100,
                render: (val: number) => `${val.toFixed(1)}s`,
              },
              {
                title: '结束时间',
                dataIndex: 'end',
                key: 'end',
                width: 100,
                render: (val: number) => `${val.toFixed(1)}s`,
              },
              {
                title: '台词内容',
                dataIndex: 'text',
                key: 'text',
              },
              {
                title: '角色',
                dataIndex: 'speaker',
                key: 'speaker',
                width: 100,
              },
            ]}
          />
        </Card>
      )}

      {/* 情绪曲线图 */}
      {state.emotionData.length > 0 && (
        <Card title="情绪曲线">
          <EmotionCurve
            data={state.emotionData}
            height={200}
          />
        </Card>
      )}
    </div>
  );
};

export default AnalyzePage;
