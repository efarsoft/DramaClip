/** 右栏·复合面板：播放器(高光标记) → 高光列表 → 转写编辑 → 操作。 */
import { tokens } from '../../styles/theme';
import { App as AntdApp, Card, Empty } from 'antd';
import { useMemo } from 'react';
import type { AnalysisResults, AsrSegment, Episode } from '@dramaclip/protocol';
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
  const highlights = useMemo(
    () => (activeEpisodeId === null ? [] : (results?.highlights?.[activeEpisodeId] ?? [])),
    [activeEpisodeId, results],
  );
  const conflicts = useMemo(
    () => (activeEpisodeId === null ? [] : (results?.conflict_scores?.[activeEpisodeId] ?? [])),
    [activeEpisodeId, results],
  );

    if (episode === null) return <EmptyDetail />;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
      <PlayerHighlightsRow
        episode={episode}
        highlights={highlights}
        videoRef={videoRef}
        onSeek={seek}
      />
      <CurveCard points={conflicts} onSeek={seek} />
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
