/** 播放器引用与定位：切集时重载，seek 到指定秒。 */
import { useCallback, useEffect, useRef } from 'react';

export function useEpisodeSeek(activeEpisodeId: string | null): {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  seek: (seconds: number) => void;
} {
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const seek = useCallback((seconds: number): void => {
    const video = videoRef.current;
    if (video !== null) video.currentTime = seconds;
  }, []);

  useEffect(() => {
    videoRef.current?.load();
  }, [activeEpisodeId]);

  return { videoRef, seek };
}
