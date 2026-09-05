import { Card, Empty, Table, Tag } from 'antd';
import { useMemo } from 'react';
import type {
  AnalysisResults,
  AsrSegment,
  ConflictScorePoint,
  HighlightSegment,
} from '@dramaclip/protocol';
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { tokens } from '../../styles/theme';

interface PanelProps {
  episodeId: string;
  results: AnalysisResults | null;
}

/** 单集结果看板：冲突曲线（recharts）+ 高光列表 + ASR 对白流（docs/desktop/01 §6）。 */
export function EpisodeResultPanel({ episodeId, results }: PanelProps) {
  const summary = results?.episodes.find((episode) => episode.episode_id === episodeId);
  const asr = results?.asr_segments?.[episodeId] ?? [];
  const highlights = results?.highlights?.[episodeId] ?? [];
  const conflicts = results?.conflict_scores?.[episodeId] ?? [];

  if (summary?.status !== 'done') {
    return (
      <Card size="small">
        <Empty description="该集尚无分析结果" />
      </Card>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <Card size="small" title={`第${String(summary.episode_number)}集 · 分析结果`}>
        <div style={{ display: 'flex', gap: 16, fontSize: 13, color: tokens.textSecondary }}>
          <span>对白 {String(summary.asr_segment_count)} 段</span>
          <span>场景 {String(summary.scene_count)} 个</span>
          <span>高光 {String(summary.highlight_count)} 个</span>
          {summary.genre !== undefined && <Tag color="blue">{summary.genre}</Tag>}
        </div>
      </Card>

      {conflicts.length > 0 && <ConflictCurve conflicts={conflicts} />}

      {highlights.length > 0 && <HighlightTable highlights={highlights} />}

      {asr.length > 0 && <DialogueStream segments={asr} />}
    </div>
  );
}

function ConflictCurve({ conflicts }: { conflicts: ConflictScorePoint[] }) {
  const data = useMemo(
    () =>
      conflicts.map((point) => ({
        time: Math.round(point.start),
        score: point.score,
        reason: point.reason ?? '',
      })),
    [conflicts],
  );
  return (
    <Card size="small" title="冲突强度曲线">
      <div style={{ width: '100%', height: 220 }}>
        <ResponsiveContainer>
          <LineChart data={data}>
            <XAxis
              dataKey="time"
              tick={{ fill: tokens.textTertiary, fontSize: 11 }}
              stroke={tokens.border}
              unit="s"
            />
            <YAxis domain={[0, 100]} tick={{ fill: tokens.textTertiary, fontSize: 11 }} stroke={tokens.border} />
            <Tooltip
              contentStyle={{ background: tokens.bgElevated, border: `1px solid ${tokens.border}` }}
              labelFormatter={(label) => `${String(Number(label))}s`}
            />
            <Line type="monotone" dataKey="score" stroke={tokens.colorPrimary} strokeWidth={2} dot />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function HighlightTable({ highlights }: { highlights: HighlightSegment[] }) {
  return (
    <Card size="small" title="高光片段（综合排序）">
      <Table
        size="small"
        pagination={false}
        rowKey={(row) => `${String(row.start)}-${String(row.end)}`}
        dataSource={[...highlights]}
        columns={[
          {
            title: '#',
            width: 48,
            render: (_text, _row, index) => index + 1,
          },
          {
            title: '时间段',
            width: 160,
            render: (_text, row) => (
              <span style={{ fontFamily: tokens.fontFamilyMono }}>
                {formatTime(row.start)} – {formatTime(row.end)}
              </span>
            ),
          },
          {
            title: '时长',
            width: 80,
            render: (_text, row) => `${(row.end - row.start).toFixed(1)}s`,
          },
          {
            title: '评分',
            width: 80,
            render: (_text, row) => <Tag color="gold">{row.score.toFixed(0)}</Tag>,
          },
          { title: '理由', render: (_text, row) => row.reason ?? '' },
        ]}
      />
    </Card>
  );
}

function DialogueStream({ segments }: { segments: AsrSegment[] }) {
  return (
    <Card size="small" title="对白流">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 360, overflowY: 'auto' }}>
        {segments.map((segment, index) => (
          <div key={`${String(segment.start)}-${String(index)}`} style={{ display: 'flex', gap: 12, fontSize: 13 }}>
            <span style={{ fontFamily: tokens.fontFamilyMono, color: tokens.textTertiary, flexShrink: 0 }}>
              {formatTime(segment.start)}
            </span>
            <span style={{ color: tokens.textPrimary }}>{segment.text}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

function formatTime(seconds: number): string {
  const total = Math.floor(seconds);
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`;
}
