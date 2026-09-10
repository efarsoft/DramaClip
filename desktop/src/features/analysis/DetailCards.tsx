/** 详情面板卡片：高光列表 + 操作。 */
import { Button, Card } from 'antd';
import { PlayerCard } from './PlayerCard';
import type { Episode, HighlightSegment } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';

export function HighlightsCard({
  highlights,
  onSeek,
}: {
  highlights: readonly HighlightSegment[];
  onSeek: (seconds: number) => void;
}): React.ReactElement {
  return (
    <Card size="small" title="高光片段（点击定位）">
      {highlights.length === 0 ? (
        <span style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary }}>暂无高光</span>
      ) : (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {highlights.map((highlight, index) => (
            <Button
              key={`${String(highlight.start)}-${String(index)}`}
              size="small"
              onClick={() => {
                onSeek(highlight.start);
              }}
            >
              {String(index + 1)}. {String(Math.round(highlight.start))}-
              {String(Math.round(highlight.end))}s · 评分 {String(Math.round(highlight.score))}
            </Button>
          ))}
        </div>
      )}
    </Card>
  );
}

export function ActionsCard({ onReanalyze }: { onReanalyze: () => void }): React.ReactElement {
  return (
    <Card size="small" title="操作">
      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <Button size="small" onClick={onReanalyze}>
          重新分析本集（重转写）
        </Button>
        <span style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary }}>
          修正转写后先「重跑语义」刷新高光；重分析会覆盖本集转写。
        </span>
      </div>
    </Card>
  );
}


export function PlayerHighlightsRow({
  episode,
  highlights,
  videoRef,
  onSeek,
}: {
  episode: Episode;
  highlights: readonly HighlightSegment[];
  videoRef: React.RefObject<HTMLVideoElement | null>;
  onSeek: (seconds: number) => void;
}): React.ReactElement {
  return (
    <div style={{ display: 'flex', gap: 14, alignItems: 'stretch' }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <PlayerCard
          videoPath={episode.source_path}
          title={`第${String(episode.episode_number)}集 · ${episode.name}`}
          highlights={highlights}
          duration={episode.duration ?? 0}
          videoRef={videoRef}
          onSeek={onSeek}
        />
      </div>
      <div style={{ flex: '0 0 300px', display: 'flex' }}>
        <HighlightsCard highlights={highlights} onSeek={onSeek} />
      </div>
    </div>
  );
}
