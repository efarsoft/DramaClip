/**
 * 情绪曲线图（简化版）
 * 使用 Recharts 库
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
  ReferenceLine,
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

// 情绪颜色映射
const EMOTION_COLORS: Record<string, string> = {
  joy: '#FFD700',
  sadness: '#4169E1',
  anger: '#FF4500',
  fear: '#8B008B',
  surprise: '#FF69B4',
  disgust: '#9ACD32',
  neutral: '#808080',
};

export const EmotionCurve: React.FC<EmotionCurveProps> = ({
  data,
  height = 200,
}) => {
  if (!data || data.length === 0) {
    return (
      <div style={{ textAlign: 'center', paddingTop: 32, paddingBottom: 32, color: 'rgba(0,0,0,0.45)' }}>
        暂无情绪数据
      </div>
    );
  }

  // 准备图表数据
  const chartData = data.map((p) => ({
    time: `${Math.floor(p.timestamp / 60)}:${(p.timestamp % 60).toFixed(0).padStart(2, '0')}`,
    intensity: p.intensity * 100,
    emotion: p.emotion,
  }));

  // 自定义tooltip
  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      const point = data.find(
        (p) => `${Math.floor(p.timestamp / 60)}:${(p.timestamp % 60).toFixed(0).padStart(2, '0')}` === label
      );
      const emotionLabels: Record<string, string> = {
        joy: '喜悦',
        sadness: '悲伤',
        anger: '愤怒',
        fear: '恐惧',
        surprise: '惊讶',
        disgust: '厌恶',
        neutral: '中性',
      };
      return (
        <div
          style={{
            backgroundColor: '#fff',
            padding: 8,
            border: '1px solid #f0f0f0',
            borderRadius: 4,
          }}
        >
          <span style={{ fontSize: 12 }}>{label}</span>
          <div>情绪: {point ? emotionLabels[point.emotion] || point.emotion : ''}</div>
          <div>强度: {payload[0]?.value?.toFixed(0)}%</div>
        </div>
      );
    }
    return null;
  };

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={chartData} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="time" />
        <YAxis
          domain={[0, 100]}
          tickFormatter={(value: number) => `${value}%`}
        />
        <Tooltip content={<CustomTooltip />} />
        <Legend />
        <Line
          type="monotone"
          dataKey="intensity"
          stroke="#8884d8"
          strokeWidth={2}
          dot={(props: any) => {
            const point = data[props.index];
            const color = point ? EMOTION_COLORS[point.emotion] || '#808080' : '#808080';
            return (
              <circle
                cx={props.cx}
                cy={props.cy}
                r={4}
                fill={color}
                stroke="#fff"
                strokeWidth={1}
              />
            );
          }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
};

export default EmotionCurve;
