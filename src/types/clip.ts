import type { HighlightSegment } from './analysis';

// 剪辑方案
export type ClipScheme = 
  | 'original_narration'  // 原片直剪
  | 'hybrid_narration'    // 混合解说
  | 'full_narration'      // 全解说
  | 'all_narrations';     // 全部生成

// 剪辑任务状态
export type ClipTaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

// 剪辑任务信息
export interface ClipTaskInfo {
  task_id: string;
  status: ClipTaskStatus;
  progress: number;
  phase?: string;
  message?: string;
  output_path?: string;
  extra_outputs?: {
    hybrid?: string;
    full?: string;
  };
}

// 剪辑推荐结果
export interface ClipRecommendation {
  episode_count: number;
  episode_type: 'single' | 'multi' | 'unknown';
  recommended_scheme: ClipScheme;
  confidence: number;
  reasons: string[];
  alternatives: ClipScheme[];
  recommended_modes: ClipScheme[];
}

// 剪辑参数
export interface ClipParams {
  output_duration?: number;    // 目标时长（秒）
  target_duration?: number;   // 同上，兼容旧接口
  clip_mode?: 'highlight' | 'transition' | 'narration';
  output_size?: '16:9' | '9:16' | '1:1';
  output_quality?: '720p' | '1080p' | '2K' | '4K';
  num_versions?: number;
  segments?: HighlightSegment[];
  selected_segments?: HighlightSegment[];
}

// 剪辑模式配置
export interface ClipModeConfig {
  id: string;
  name: string;
  desc: string;
  type: ClipScheme;
  tags: string[];
  icon: React.ReactNode;
  priority: number;
}

// 剪辑模式常量
export const CLIP_MODES: ClipModeConfig[] = [
  {
    id: 'mode-original',
    name: '原片解说',
    desc: '提取视频情节和高光，通过截取和合并原视频进行剪辑，全程使用原声',
    type: 'original_narration',
    tags: ['原声拼接', '保留原汁原味', '适合剧情片'],
    icon: null as any,
    priority: 0,
  },
  {
    id: 'mode-hybrid',
    name: '交叉解说',
    desc: 'AI 生成解说词，结合原视频高光，形成混合式 AI 解说 + 原声效果',
    type: 'hybrid_narration',
    tags: ['AI 解说', '原声混音', '适合解说类'],
    icon: null as any,
    priority: 1,
  },
  {
    id: 'mode-full',
    name: '全片解说',
    desc: 'AI 生成全部解说文案并配音，不使用原声，纯 AI 旁白风格',
    type: 'full_narration',
    tags: ['全 AI 配音', '几分钟看完', '适合速览'],
    icon: null as any,
    priority: 2,
  },
  {
    id: 'mode-all',
    name: '全部生成',
    desc: '一次性生成以上三种模式的剪辑结果，对比择优或同时分发',
    type: 'all_narrations',
    tags: ['一键三连', '批量输出', '效率最高'],
    icon: null as any,
    priority: 3,
  },
];

// 导出预设
export interface ExportPreset {
  resolution: string;
  bitrate: string;
  fps: number;
  format: 'mp4' | 'webm' | 'gif';
}

export const EXPORT_PRESETS: Record<string, ExportPreset> = {
  '1080p': { resolution: '1920x1080', bitrate: '8M', fps: 30, format: 'mp4' },
  '1080p_v': { resolution: '1080x1920', bitrate: '6M', fps: 30, format: 'mp4' },
  '720p': { resolution: '1280x720', bitrate: '4M', fps: 30, format: 'mp4' },
  '4k': { resolution: '3840x2160', bitrate: '20M', fps: 30, format: 'mp4' },
  'gif': { resolution: '640x360', bitrate: '2M', fps: 15, format: 'gif' },
};

// 复用分析类型
export type { HighlightSegment } from './analysis';
