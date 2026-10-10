/** 右栏·复合面板：播放器(高光标记) → 高光列表 → 转写编辑 → 操作。 */
import { tokens } from '../../styles/theme';
import { App as AntdApp, Alert, Card, Empty } from 'antd';
import { useMemo } from 'react';
import type { AnalysisResults, AsrSegment, Episode, VisualFrame } from '@dramaclip/protocol';
import { ActionsCard, PlayerHighlightsRow } from './DetailCards';
import { reanalyzeEpisode } from './reanalyze';
import { CurveCard } from './CurveCard';
import { TranscriptCard } from './TranscriptCard';
import { useEpisodeSeek } from './useEpisodeSeek';
import { useResyncSemantic } from './useResyncSemantic';
import { useTranscriptSave } from './useTranscriptSave';

interface DetailProps {
  projectId: string;
  episodes: Episode[];
  activeEpisodeId: string | null;
  results: AnalysisResults | null;
  onReload: () => void;
}

/** 选中剧集的详情面板。 */
export function EpisodeDetail({
  projectId,
  episodes,
  activeEpisodeId,
  results,
  onReload,
}: DetailProps): React.ReactElement {
  const { message } = AntdApp.useApp();
  const notifyError = (text: string): void => {
    message.error(text);
  };
  const notifyOk = (text: string): void => {
    message.success(text);
  };
  const { videoRef, seek } = useEpisodeSeek(activeEpisodeId);
  const resync = useResyncSemantic(projectId, activeEpisodeId ?? '', onReload);
  const transcript = transcriptOf(results, activeEpisodeId);
  const saveEdit = useTranscriptSave(projectId, activeEpisodeId, transcript, onReload);
  const episode = episodes.find((item) => item.id === activeEpisodeId) ?? null;
  const clipping = results?.episodes.find((item) => item.episode_id === activeEpisodeId)?.clipping === true;
  const highlights = useMemo(
    () => (activeEpisodeId === null ? [] : (results?.highlights?.[activeEpisodeId] ?? [])),
    [activeEpisodeId, results],
  );
  const conflicts = useMemo(
    () => (activeEpisodeId === null ? [] : (results?.conflict_scores?.[activeEpisodeId] ?? [])),
    [activeEpisodeId, results],
  );
  const visualTrack = useMemo(
    () => (activeEpisodeId === null ? undefined : results?.visual_tracks?.[activeEpisodeId]),
    [activeEpisodeId, results],
  );
  const visualFrames = visualTrack?.frames ?? [];

    if (episode === null) return <EmptyDetail />;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
      {clipping && (
        <Alert
          type="warning"
          showIcon
          title="这集源音频已经削顶。成片限幅只能压电平，不能把平顶长回来。"
        />
      )}
      <PlayerHighlightsRow
        episode={episode}
        highlights={highlights}
        videoRef={videoRef}
        onSeek={seek}
      />
      <CurveCard points={conflicts} onSeek={seek} />
      {visualFrames.length > 0 && (
        <VisualTrackCard frames={visualFrames} engine={visualTrack?.engine} onSeek={seek} />
      )}
      <BottomCards
        transcript={transcript}
        resyncing={resync.running}
        onSeek={seek}
        onSaveEdit={saveEdit}
        onRerun={() => {
          runResync(resync, notifyError);
        }}
        onReanalyze={() => {
          reanalyzeEpisode(projectId, episode.id, episode.episode_number, notifyOk, notifyError);
        }}
      />
    </div>
  );
}

interface BottomProps {
  transcript: readonly AsrSegment[];
  resyncing: boolean;
  onSeek: (seconds: number) => void;
  onSaveEdit: (index: number, text: string) => void;
  onRerun: () => void;
  onReanalyze: () => void;
}

function BottomCards(props: BottomProps): React.ReactElement {
  return (
    <>
      <TranscriptCard
        segments={props.transcript}
        resyncing={props.resyncing}
        onSeek={props.onSeek}
        onSaveEdit={props.onSaveEdit}
        onResync={props.onRerun}
      />
      <ActionsCard onReanalyze={props.onReanalyze} />
    </>
  );
}

function EmptyDetail(): React.ReactElement {
  return (
    <Card size="small" style={{ minHeight: 300 }}>
      <Empty description="从左侧选择一集查看详情" />
    </Card>
  );
}

function runResync(
  resync: { run: () => Promise<void> },
  onError: (text: string) => void,
): void {
  resync.run().catch((error: unknown) => {
    onError(error instanceof Error ? error.message : String(error));
  });
}

function transcriptOf(
  results: AnalysisResults | null,
  activeEpisodeId: string | null,
): readonly { start: number; end: number; text: string }[] {
  if (activeEpisodeId === null || results === null) return [];
  return results.asr_segments?.[activeEpisodeId] ?? [];
}

/** 画面轨卡（P2b）：逐帧画面实据，点时间戳跳播；视觉档关闭/未跑的集不出现。 */
function VisualTrackCard({
  frames,
  engine,
  onSeek,
}: {
  frames: readonly VisualFrame[];
  engine?: string;
  onSeek: (seconds: number) => void;
}): React.ReactElement {
  const mono = { fontFamily: tokens.fontFamilyMono } as const;
  return (
    <Card
      size="small"
      title={
        <span>
          画面轨{' '}
          <span style={{ ...mono, color: tokens.textTertiary }}>
            {String(frames.length)} 帧{engine ? ` · ${engine}` : ''}
          </span>
        </span>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs }}>
        {frames.map((frame) => (
          <div
            key={`${frame.t}-${frame.scene}`}
            style={{ display: 'flex', gap: tokens.spaceSm, alignItems: 'baseline' }}
          >
            <button
              type="button"
              onClick={() => {
                onSeek(frame.t);
              }}
              style={{
                background: 'none',
                border: 'none',
                color: tokens.colorPrimary,
                cursor: 'pointer',
                padding: 0,
                fontSize: tokens.text.meta.size,
                fontFamily: tokens.fontFamilyMono,
                flexShrink: 0,
              }}
            >
              {`${frame.t.toFixed(1)}s`}
            </button>
            <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textSecondary }}>
              {[
                frame.shot,
                frame.scene,
                frame.people,
                frame.action,
                frame.mood ? `（${frame.mood}）` : '',
              ]
                .filter((part) => part !== '')
                .join(' ')}
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}
