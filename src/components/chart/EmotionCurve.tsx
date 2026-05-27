/**
 * 情绪曲线图 — 视频分析模块
 * 基于 Recharts 绘制高精时间序列曲线
 */

import React from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';

interface EmotionPoint {
  timestamp: number;
  emotion: string;
  intensity: number;
}

interface EmotionCurveProps {
  data: EmotionPoint[];
  height?: number;
}

// 高端、高对比度暗色系情绪颜色映射
const EMOTION_COLORS: Record<string, string> = {
  joy: '#fbbf24',          // 喜悦 (Ambitious Gold)
  sadness: '#3b82f6',      // 悲伤 (Sleek Blue)
  anger: '#ef4444',        // 愤怒 (Premium Red)
  fear: '#a855f7',         // 恐惧 (Vibrant Purple)
  surprise: '#ec4899',     // 惊讶 (Rose Pink)
  disgust: '#10b981',      // 厌恶 (Emerald Green)
  neutral: '#64748b',      // 平静/中性 (Sleek Slate)
  helplessness: '#8b5cf6', // 无奈 (Soft Violet)
  ambivalence: '#14b8a6',  // 纠结 (Sleek Teal)
  jealousy: '#f97316',     // 嫉妒 (Orange)
  relief: '#84cc16',       // 释然 (Lime Green)
  excitement: '#f43f5e',   // 兴奋 (Rose Red)
  tenderness: '#fda4af',   // 温柔 (Baby Pink)
  contempt: '#4b5563',     // 轻蔑 (Cool Gray)
  anticipation: '#eab308', // 期待 (Bright Yellow)
};

export const EmotionCurve: React.FC<EmotionCurveProps> = ({
  data,
  height = 220,
}) => {
  if (!data || data.length === 0) {
    return (
      <div style={{ textAlign: 'center', paddingTop: 40, paddingBottom: 40, color: 'rgba(255,255,255,0.25)' }}>
        暂无情绪数据
      </div>
    );
  }

  // 按时间戳正序排序，确保曲线连贯不交叉
  const sortedData = [...data].sort((a, b) => a.timestamp - b.timestamp);

  // 准备图表数据，增加原始 float timestamp 并乘 100 做百分比，对平静状态引入有机自然波动
  const chartData = sortedData.map((p) => {
    const rawIntensity = p.intensity * 100;
    let displayIntensity = rawIntensity;
    if (p.emotion === 'neutral') {
      // 基于时间戳生成决定性、连贯的微幅正弦波动（在 27% ~ 33% 间平滑起伏）
      const wave = Math.sin(p.timestamp * 0.4) * 3;
      displayIntensity = 30 + wave;
    }
    return {
      timestamp: p.timestamp,
      intensity: displayIntensity,
      rawIntensity: rawIntensity,
      emotion: p.emotion,
    };
  });

  // 自定义高端 Tooltip
  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      // 匹配当前时间点
      const point = sortedData.find((p) => Math.abs(p.timestamp - label) < 0.01) || payload[0]?.payload;
      
      const emotionLabels: Record<string, string> = {
        joy: '喜悦',
        sadness: '悲伤',
        anger: '愤怒',
        fear: '恐惧',
        surprise: '惊讶',
        disgust: '厌恶',
        neutral: '平静',
        helplessness: '无奈',
        ambivalence: '纠结',
        jealousy: '嫉妒',
        relief: '释然',
        excitement: '兴奋',
        tenderness: '温柔',
        contempt: '轻蔑',
        anticipation: '期待',
      };

      const timeStr = (() => {
        const val = Number(label);
        const min = Math.floor(val / 60);
        const sec = Math.floor(val % 60);
        return `${min}:${sec.toString().padStart(2, '0')}`;
      })();

      const emotionKey = point?.emotion || 'neutral';
      const displayEmotion = emotionLabels[emotionKey] || emotionKey;
      const color = EMOTION_COLORS[emotionKey] || '#64748b';

      return (
        <div
          style={{
            backgroundColor: 'rgba(15, 23, 42, 0.95)',
            padding: '10px 14px',
            border: '1px solid rgba(255, 255, 255, 0.08)',
            borderRadius: 8,
            boxShadow: '0 4px 16px rgba(0, 0, 0, 0.35)',
            backdropFilter: 'blur(8px)',
          }}
        >
          <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4, fontFamily: "'JetBrains Mono', monospace" }}>
            ⏱️ 时间点: {timeStr} ({Number(label).toFixed(2)}s)
          </div>
          <div style={{ color: '#f1f5f9', fontSize: 13, display: 'flex', alignItems: 'center', gap: 6 }}>
            <span>情绪类型:</span>
            <span style={{ fontWeight: 700, color }}>
              {displayEmotion}
            </span>
          </div>
          <div style={{ color: '#cbd5e1', fontSize: 12, marginTop: 4 }}>
            情绪强度: <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, color: '#38bdf8' }}>{point?.intensity !== undefined ? (point.intensity * 100).toFixed(0) : payload[0]?.payload?.rawIntensity?.toFixed(0)}%</span>
          </div>
        </div>
      );
    }
    return null;
  };

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={chartData} margin={{ top: 10, right: 20, left: 0, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.03)" />
        <XAxis
          dataKey="timestamp"
          type="number"
          domain={['auto', 'auto']}
          stroke="rgba(255,255,255,0.25)"
          tickFormatter={(value: number) => {
            const min = Math.floor(value / 60);
            const sec = Math.floor(value % 60);
            return `${min}:${sec.toString().padStart(2, '0')}`;
          }}
          style={{ fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
        />
        <YAxis
          domain={[0, 100]}
          stroke="rgba(255,255,255,0.25)"
          tickFormatter={(value: number) => `${value}%`}
          style={{ fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
        />
        <Tooltip content={<CustomTooltip />} />
        <Line
          type="monotone"
          dataKey="intensity"
          stroke="url(#emotionLineGradient)"
          strokeWidth={3.5}
          activeDot={{ r: 7, stroke: '#fff', strokeWidth: 2 }}
          dot={(props: any) => {
            const point = chartData[props.index];
            if (!point) return null;
            const isNeutral = point.emotion === 'neutral';
            const color = EMOTION_COLORS[point.emotion] || '#64748b';

            if (isNeutral) {
              // 平静点：绘制为超小、半透明的微尘点，退为背景，杜绝“念珠链”视觉杂乱
              return (
                <circle
                  key={props.key || props.index}
                  cx={props.cx}
                  cy={props.cy}
                  r={1.5}
                  fill="rgba(100, 116, 139, 0.3)"
                  stroke="none"
                />
              );
            }

            // 情绪波动点：绘制为带有发光呼吸光环的璀璨彩色锚点
            return (
              <g key={props.key || props.index}>
                <circle
                  cx={props.cx}
                  cy={props.cy}
                  r={6}
                  fill={color}
                  opacity={0.3}
                  style={{ filter: 'blur(1px)' }}
                />
                <circle
                  cx={props.cx}
                  cy={props.cy}
                  r={4}
                  fill={color}
                  stroke="#ffffff"
                  strokeWidth={1.5}
                  style={{ filter: 'drop-shadow(0px 0px 3px ' + color + ')' }}
                />
              </g>
            );
          }}
        />
        
        {/* 垂直色彩渐变：使曲线颜色完全契合情绪波动的起伏强度 */}
        <defs>
          <linearGradient id="emotionLineGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f43f5e" stopOpacity={0.95} /> {/* 极度高涨 - 玫瑰红 */}
            <stop offset="50%" stopColor="#c084fc" stopOpacity={0.85} /> {/* 中度起伏 - 炫彩紫 */}
            <stop offset="100%" stopColor="#06b6d4" stopOpacity={0.6} /> {/* 平静基线 - 湖水蓝 */}
          </linearGradient>
        </defs>
      </LineChart>
    </ResponsiveContainer>
  );
};

export default EmotionCurve;
