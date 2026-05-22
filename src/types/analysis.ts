/**
 * 分析相关类型定义
 */

// ASR (自动语音识别) 类型
export interface ASRSegment {
  id: string;
  text: string;
  start: number;  // 开始时间（秒）
  end: number;    // 结束时间（秒）
  speaker?: string;
  confidence?: number;
}

export interface ASRResult {
  segments: ASRSegment[];
  language?: string;
  duration?: number;
  full_text?: string;
}

// 情绪分析类型
export interface EmotionPoint {
  timestamp: number;
  emotion: 'positive' | 'negative' | 'neutral' | 'mixed';
  intensity: number;  // 0-1 之间
}

export interface EmotionResult {
  emotion_curve: EmotionPoint[];
  summary?: string;
  peak_moments?: number[];  // 高潮时间点
  average_intensity?: number;
}

// 高光片段类型
export interface HighlightSegment {
  id?: string;
  video_path: string;
  start_time: number;
  end_time: number;
  duration: number;
  score: number;
  audio_score: number;
  emotion_score: number;
  visual_score: number;
  rhythm_score: number;
  subtitle_text?: string;
  reason?: string;
  segment_id?: string;
}

// 分析结果
export interface AnalysisResults {
  asr?: ASRResult;
  emotion?: EmotionResult;
  highlights?: HighlightSegment[];
}

// 分析任务状态
export type AnalysisTaskStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface AnalysisTaskInfo {
  task_id: string;
  status: AnalysisTaskStatus;
  progress: number;
  phase?: string;
  message?: string;
  results?: AnalysisResults;
  error?: string;
}

// 分析阶段
export const ANALYSIS_PHASE_LABELS: Record<string, string> = {
  init: '初始化',
  asr: '语音识别',
  emotion: '情绪分析',
  highlight: '高光识别',
  completed: '分析完成',
  failed: '分析失败',
  idle: '准备就绪',
  error: '错误',
};
