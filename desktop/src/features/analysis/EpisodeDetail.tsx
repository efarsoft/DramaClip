/** 右栏·复合面板：播放器(高光标记) → 高光列表 → 转写编辑 → 操作。 */
import { App as AntdApp, Card, Empty } from 'antd';
import { useMemo } from 'react';
import type { AnalysisResults, Episode } from '@dramaclip/protocol';
import { ActionsCard, HighlightsCard } from './DetailCards';
import { reanalyzeEpisode } from './reanalyze';
import { PlayerCard } from './PlayerCard';
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
  const { videoRef, seek } = useEpisodeSeek(activeEpisodeId);
  const resync = useResyncSemantic(projectId, activeEpisodeId ?? '', onReload);
  const transcript = transcriptOf(results, activeEpisodeId);
  const saveEdit = useTranscriptSave(projectId, activeEpisodeId, transcript, onReload);
  const episode = episodes.find((item) => item.id === activeEpisodeId) ?? null;
  const highlights = useMemo(
    () => (activeEpisodeId === null ? [] : (results?.highlights?.[activeEpisodeId] ?? [])),
    [activeEpisodeId, results],
  );

    if (episode === null) return <EmptyDetail />;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <PlayerCard
        videoPath={episode.source_path}
        title={`第${String(episode.episode_number)}集 · ${episode.name}`}
        highlights={highlights}
        duration={episode.duration ?? 0}
        videoRef={videoRef}
        onSeek={seek}
      />
      <HighlightsCard highlights={highlights} onSeek={seek} />
      <TranscriptCard
        segments={transcript}
        resyncing={resync.running}
        onSeek={seek}
        onSaveEdit={saveEdit}
        onResync={() => {
          resync.run().catch((error: unknown) => {
            message.error(error instanceof Error ? error.message : String(error));
          });
        }}
      />
      <ActionsCard
        onReanalyze={() => {
          reanalyzeEpisode(
            projectId,
            episode.id,
            episode.episode_number,
            (text) => {
              message.success(text);
            },
            (text) => {
              message.error(text);
            },
          );
        }}
      />
    </div>
  );
}

function EmptyDetail(): React.ReactElement {
  return (
    <Card size="small" style={{ minHeight: 300 }}>
      <Empty description="从左侧选择一集查看详情" />
    </Card>
  );
}

function transcriptOf(
  results: AnalysisResults | null,
  activeEpisodeId: string | null,
): readonly { start: number; end: number; text: string }[] {
  if (activeEpisodeId === null || results === null) return [];
  return results.asr_segments?.[activeEpisodeId] ?? [];
}
