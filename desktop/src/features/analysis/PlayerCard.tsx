/** 播放器卡片：视频 + 高光标记轨道（点击定位）。 */
import { Card } from 'antd';
import type { HighlightSegment } from '@dramaclip/protocol';
import { mediaUrl } from '../../services/client';
import { tokens } from '../../styles/theme';

export function PlayerCard({
  videoPath,
  title,
  highlights,
  duration,
  videoRef,
  onSeek,
}: {
  videoPath: string;
  title: string;
  highlights: readonly HighlightSegment[];
  duration: number;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  onSeek: (seconds: number) => void;
}): React.ReactElement {
  const total = Math.max(duration, 1);
  return (
    <Card size="small" title={title} style={{ height: '100%' }}>
      <video
        ref={videoRef}
        src={mediaUrl(videoPath)}
        controls
        style={{ width: '100%', maxHeight: 380, borderRadius: 8, background: '#000' }}
      />
      <div
        style={{
          position: 'relative',
          height: 16,
          marginTop: 10,
          borderRadius: 4,
          background: tokens.bgInput,
          overflow: 'hidden',
        }}
      >
        {highlights.map((highlight, index) => (
          <span
            key={`${String(highlight.start)}-${String(index)}`}
            title={`${String(Math.round(highlight.start))}-${String(Math.round(highlight.end))}s`}
            onClick={() => {
              onSeek(highlight.start);
            }}
            style={{
              position: 'absolute',
              left: `${String((highlight.start / total) * 100)}%`,
              width: `${String(Math.max(((highlight.end - highlight.start) / total) * 100, 1))}%`,
              top: 0,
              bottom: 0,
              background: tokens.colorWarning,
              opacity: 0.75,
              cursor: 'pointer',
            }}
          />
        ))}
      </div>
    </Card>
  );
}
