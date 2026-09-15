/** 冲突强度曲线：渐变面积图，点击定位播放。 */
import { Card } from 'antd';
import { useMemo } from 'react';
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { ConflictScorePoint } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';

interface ChartPoint {
  readonly time: number;
  readonly score: number;
}

function toChartData(points: readonly ConflictScorePoint[]): ChartPoint[] {
  return [...points]
    .sort((a, b) => a.start - b.start)
    .map((p) => ({ time: Math.round(p.start), score: p.score }));
}

const TOOLTIP_STYLE = {
  background: tokens.bgElevated,
  border: `1px solid ${tokens.border}`,
  borderRadius: tokens.radiusControl,
  fontSize: tokens.fontCaption,
} as const;

function handleActivate(state: { activeLabel?: number | string } | null, onSeek: (s: number) => void): void {
  if (state?.activeLabel === undefined) return;
  onSeek(Number(state.activeLabel));
}

export function CurveCard({
  points,
  onSeek,
}: {
  points: readonly ConflictScorePoint[];
  onSeek: (seconds: number) => void;
}): React.ReactElement {
  const data = useMemo(() => toChartData(points), [points]);
  const peak = data.reduce((max, d) => Math.max(max, d.score), 0);

  return (
    <Card
      size="small"
      title="冲突强度曲线"
      styles={{ body: { padding: '10px 14px 6px', height: '100%' } }}
    >
      <div style={{ height: 170 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart
            data={data}
            margin={{ top: 6, right: 6, left: -18, bottom: 0 }}
            onClick={(state) => {
              handleActivate(state, onSeek);
            }}
          >
            <defs>{chartGradient()}</defs>
            {chartAxes()}
            {chartArea()}
          </AreaChart>
        </ResponsiveContainer>
      </div>
      {peak > 0 && (
        <div style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary, marginTop: tokens.spaceXs }}>
          峰值 {String(peak)} 分 · 点击曲线可定位播放
        </div>
      )}
    </Card>
  );
}

function chartAxes(): React.ReactElement {
  return (
    <>
      <XAxis
        dataKey="time"
        tick={{ fill: tokens.textTertiary, fontSize: tokens.fontMicro }}
        stroke={tokens.border}
      />
      <YAxis
        domain={[0, 100]}
        tick={{ fill: tokens.textTertiary, fontSize: tokens.fontMicro }}
        stroke={tokens.border}
      />
      <Tooltip
        contentStyle={{ ...TOOLTIP_STYLE }}
        labelFormatter={(label) => `${String(Number(label))}s`}
        formatter={(value) => [`${String(value)} 分`, '冲突强度']}
      />
    </>
  );
}

function chartGradient(): React.ReactElement {
  return (
    <linearGradient id="curveFill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stopColor={tokens.colorPrimary} stopOpacity={0.32} />
      <stop offset="100%" stopColor={tokens.colorPrimary} stopOpacity={0.02} />
    </linearGradient>
  );
}

function chartArea(): React.ReactElement {
  return (
    <Area
      type="monotone"
      dataKey="score"
      stroke={tokens.colorPrimary}
      strokeWidth={2}
      fill="url(#curveFill)"
      dot={false}
      activeDot={{ r: 4, fill: tokens.colorPrimary }}
    />
  );
}
