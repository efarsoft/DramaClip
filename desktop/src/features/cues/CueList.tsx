/** 逐句时间轴列表：一行一句（时间码 + 文本），有播放器（onSeek）时点击定位到那一句。
 * 工具箱（copy.srt）与成片页（output.srt）共用同一份呈现，别再各写一遍。 */
import type { ReactElement } from 'react';
import { tokens } from '../../styles/theme';
import { formatStamp } from './srt';
import type { Cue } from './srt';

export function CueList({
  cues,
  onSeek,
}: {
  cues: readonly Cue[];
  onSeek?: (seconds: number) => void;
}): ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: tokens.spaceXs,
        marginTop: tokens.spaceSm,
        maxHeight: 320,
        overflowY: 'auto',
      }}
    >
      {cues.map((cue, index) => (
        <div
          key={`${String(cue.start)}-${String(index)}`}
          onClick={onSeek === undefined ? undefined : (): void => { onSeek(cue.start); }}
          title={onSeek === undefined ? undefined : `跳到 ${formatStamp(cue.start)}`}
          style={{
            display: 'flex',
            gap: tokens.spaceSm,
            alignItems: 'baseline',
            padding: `${tokens.spaceXs} ${tokens.spaceSm}`,
            borderRadius: tokens.radiusThumb,
            background: tokens.bgInput,
            cursor: onSeek === undefined ? 'default' : 'pointer',
          }}
        >
          <span
            style={{
              flexShrink: 0,
              fontFamily: tokens.fontFamilyMono,
              fontSize: tokens.text.meta.size,
              color: tokens.textTertiary,
            }}
          >
            {formatStamp(cue.start)}
          </span>
          <span
            style={{
              fontSize: tokens.text.body.size,
              lineHeight: tokens.text.body.leading,
              color: tokens.textSecondary,
              whiteSpace: 'pre-line',
            }}
          >
            {cue.text}
          </span>
        </div>
      ))}
    </div>
  );
}
