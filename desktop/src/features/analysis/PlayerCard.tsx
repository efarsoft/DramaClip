/** 播放器卡片：视频 + 高光标记轨道（点击定位）。

视频加载失败不再是黑盒：协议侧每个拒绝分支都有 HTTP 状态码，onError 把它翻成
人话（403=围栏未收录素材根，多半是服务重启后 60s 内的缓存窗口或 project.list
没取到；404=源片被移走；其余=媒体栈拒绝该文件）——修哪层一眼可辨。
key=videoPath：换集强制重挂视频元素，杜绝「src 变了元素没重载」的残留态
（热更新/异常时序下会出现，load() 兜底治不全）。 */
import { Card } from 'antd';
import { useEffect, useState } from 'react';
import type { ReactElement } from 'react';
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
}): ReactElement {
  const total = Math.max(duration, 1);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setError(null); // 换集清上一集的报错（错误状态在卡上，不随 video 重挂消失）
  }, [videoPath]);
  return (
    <Card size="small" title={title} style={{ height: '100%' }}>
      {error !== null && (
        <div
          style={{
            padding: `${tokens.spaceXs}px ${tokens.spaceSm}px`,
            marginBottom: tokens.spaceSm,
            fontSize: tokens.text.meta.size,
            lineHeight: tokens.text.meta.leading,
            color: tokens.colorError,
            background: tokens.bgInput,
            borderRadius: tokens.radiusControl,
            wordBreak: 'break-all',
          }}
        >
          视频没加载：{error}（路径 {videoPath}）
        </div>
      )}
      <video
        key={videoPath}
        ref={videoRef}
        src={mediaUrl(videoPath)}
        controls
        onLoadedMetadata={() => {
          setError(null);
        }}
        onError={(event) => {
          setError(describeVideoError(event.currentTarget.error?.code, videoPath));
        }}
        style={{ width: '100%', maxHeight: 380, borderRadius: tokens.radiusControl, background: tokens.posterBase }}
      />
      <div
        style={{
          position: 'relative',
          height: 16,
          marginTop: tokens.spaceSm,
          borderRadius: tokens.radiusThumb,
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

/** 媒体栈错误码 → 人话（按最可能的成因排序；协议各拒绝分支见 preview-protocol.ts）。 */
function describeVideoError(code: number | undefined, videoPath: string): string {
  const ext = videoPath.split('.').pop()?.toLowerCase() ?? '';
  switch (code) {
    case 1:
      return '加载被中断（多半是切换/重挂时序，等一秒或点一下播放）';
    case 2:
      return '网络层错误——dramaclip 协议返回了非 2xx（403=素材根围栏还没收录这个目录，'
        + '常见于服务重启后一分钟内的缓存窗口，稍等重试；404=源片文件被移动或删除）';
    case 3:
      return '解码失败——文件在但内容读不动（源片损坏或下载未完成）';
    case 4:
    default:
      return ext === 'mkv'
        ? '媒体栈不认这个容器（mkv 常见，换 mp4/webm 源）'
        : '媒体栈拒绝该源（格式或响应不合规）';
  }
}
