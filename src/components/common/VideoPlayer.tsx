/**
 * 视频播放器组件
 * 支持模态框全屏播放和内联预览两种模式
 * 使用 dramaclip:// 自定义协议访问本地视频文件
 */

import React, { useRef, useEffect, useState, useCallback } from 'react';
import { Modal, Slider, Tooltip, message } from 'antd';
import {
  PlayCircleOutlined,
  PauseCircleOutlined,
  FullscreenOutlined,
  FullscreenExitOutlined,
  SoundOutlined,
  MutedOutlined,
  StepForwardOutlined,
  StepBackwardOutlined,
  CloseOutlined,
} from '@ant-design/icons';
import { videoUrl } from '../../services/ipc';

const CYAN = '#00d4ff';
const PURPLE = '#7c3aed';

// ─── 工具函数 ───

function formatTime(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return '0:00';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) {
    return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }
  return `${m}:${s.toString().padStart(2, '0')}`;
}

// ─── 内联迷你预览 ───

interface MiniPreviewProps {
  filePath: string;
  width?: number;
  height?: number;
  startTime?: number;
  endTime?: number;
  onClick?: () => void;
}

export const MiniPreview: React.FC<MiniPreviewProps> = ({
  filePath,
  width = 160,
  height = 90,
  startTime,
  endTime,
  onClick,
}) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const handleLoaded = () => {
      setLoaded(true);
      // 跳到 startTime 或 1 秒处获取缩略图帧
      const seekTime = startTime != null && startTime > 0 ? startTime : 1;
      video.currentTime = seekTime;
    };

    const handleError = () => setError(true);

    video.addEventListener('loadedmetadata', handleLoaded);
    video.addEventListener('error', handleError);

    return () => {
      video.removeEventListener('loadedmetadata', handleLoaded);
      video.removeEventListener('error', handleError);
    };
  }, [startTime]);

  // 到达 seek 位置后暂停
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !loaded) return;

    const handleSeeked = () => {
      video.pause();
    };

    video.addEventListener('seeked', handleSeeked);
    return () => video.removeEventListener('seeked', handleSeeked);
  }, [loaded]);

  if (error) {
    return (
      <div
        style={{
          width, height, borderRadius: 8,
          background: 'rgba(255,255,255,0.04)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          cursor: onClick ? 'pointer' : 'default',
        }}
        onClick={onClick}
      >
        <PlayCircleOutlined style={{ fontSize: 20, color: '#4a5a7a' }} />
      </div>
    );
  }

  return (
    <div
      style={{
        width, height, borderRadius: 8, overflow: 'hidden',
        position: 'relative', cursor: onClick ? 'pointer' : 'default',
        background: '#000',
      }}
      onClick={onClick}
    >
      <video
        ref={videoRef}
        src={videoUrl(filePath)}
        preload="metadata"
        muted
        playsInline
        style={{
          width: '100%', height: '100%', objectFit: 'cover',
          opacity: loaded ? 1 : 0,
          transition: 'opacity 0.3s',
        }}
      />
      {/* 播放按钮覆盖层 */}
      <div style={{
        position: 'absolute', inset: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'rgba(0,0,0,0.25)',
        opacity: 0, transition: 'opacity 0.2s',
      }}
        className="mini-preview-overlay"
      />
      {!loaded && (
        <div style={{
          position: 'absolute', inset: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: 'rgba(255,255,255,0.04)',
        }}>
          <PlayCircleOutlined style={{ fontSize: 20, color: '#4a5a7a' }} />
        </div>
      )}
      {/* 时间范围标签 */}
      {startTime != null && endTime != null && (
        <div style={{
          position: 'absolute', bottom: 4, right: 4,
          padding: '1px 6px', borderRadius: 4,
          background: 'rgba(0,0,0,0.7)',
          color: '#c8d0dc', fontSize: 10,
          fontFamily: "'JetBrains Mono', monospace",
        }}>
          {formatTime(endTime - startTime)}
        </div>
      )}
    </div>
  );
};


// ─── 模态框视频播放器 ───

interface VideoPlayerModalProps {
  /** 本地文件路径 */
  filePath: string;
  /** 视频名称，显示在标题栏 */
  title?: string;
  /** 起始播放时间（秒） */
  startTime?: number;
  /** 结束时间（秒），到达后暂停 */
  endTime?: number;
  /** 是否显示模态框 */
  open: boolean;
  /** 关闭回调 */
  onClose: () => void;
}

export const VideoPlayerModal: React.FC<VideoPlayerModalProps> = ({
  filePath,
  title,
  startTime,
  endTime,
  open,
  onClose,
}) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1);

  // 当模态框打开时，初始化视频
  useEffect(() => {
    if (!open) return;
    const video = videoRef.current;
    if (!video) return;

    const handleLoaded = () => {
      setDuration(video.duration);
      if (startTime != null && startTime > 0) {
        video.currentTime = startTime;
      }
    };

    const handleTimeUpdate = () => {
      setCurrentTime(video.currentTime);
      // 到达 endTime 时暂停
      if (endTime != null && video.currentTime >= endTime) {
        video.pause();
        setPlaying(false);
      }
    };

    const handleEnded = () => setPlaying(false);
    const handlePlay = () => setPlaying(true);
    const handlePause = () => setPlaying(false);

    video.addEventListener('loadedmetadata', handleLoaded);
    video.addEventListener('timeupdate', handleTimeUpdate);
    video.addEventListener('ended', handleEnded);
    video.addEventListener('play', handlePlay);
    video.addEventListener('pause', handlePause);

    return () => {
      video.removeEventListener('loadedmetadata', handleLoaded);
      video.removeEventListener('timeupdate', handleTimeUpdate);
      video.removeEventListener('ended', handleEnded);
      video.removeEventListener('play', handlePlay);
      video.removeEventListener('pause', handlePause);
    };
  }, [open, startTime, endTime]);

  // 关闭时暂停视频
  useEffect(() => {
    if (!open && videoRef.current) {
      videoRef.current.pause();
      setPlaying(false);
    }
  }, [open]);

  const togglePlay = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      video.play().catch(() => message.warning('视频播放失败'));
    } else {
      video.pause();
    }
  }, []);

  const seek = useCallback((time: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = Math.max(0, Math.min(time, duration));
  }, [duration]);

  const skip = useCallback((delta: number) => {
    seek(currentTime + delta);
  }, [currentTime, seek]);

  const toggleMute = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    video.muted = !muted;
    setMuted(!muted);
  }, [muted]);

  const changeVolume = useCallback((v: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.volume = v;
    setVolume(v);
    if (v > 0 && muted) {
      video.muted = false;
      setMuted(false);
    }
  }, [muted]);

  const toggleFullscreen = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    if (!fullscreen) {
      container.requestFullscreen?.();
      setFullscreen(true);
    } else {
      document.exitFullscreen?.();
      setFullscreen(false);
    }
  }, [fullscreen]);

  const cyclePlaybackRate = useCallback(() => {
    const rates = [0.5, 0.75, 1, 1.25, 1.5, 2];
    const idx = rates.indexOf(playbackRate);
    const next = rates[(idx + 1) % rates.length];
    if (videoRef.current) videoRef.current.playbackRate = next;
    setPlaybackRate(next);
  }, [playbackRate]);

  // 快捷键
  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      switch (e.key) {
        case ' ':
        case 'k':
          e.preventDefault();
          togglePlay();
          break;
        case 'ArrowLeft':
          e.preventDefault();
          skip(-5);
          break;
        case 'ArrowRight':
          e.preventDefault();
          skip(5);
          break;
        case 'ArrowUp':
          e.preventDefault();
          changeVolume(Math.min(1, volume + 0.1));
          break;
        case 'ArrowDown':
          e.preventDefault();
          changeVolume(Math.max(0, volume - 0.1));
          break;
        case 'm':
          toggleMute();
          break;
        case 'f':
          toggleFullscreen();
          break;
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [open, togglePlay, skip, changeVolume, toggleMute, toggleFullscreen]);

  // 进度条拖拽
  const handleSliderChange = useCallback((value: number) => {
    seek(value);
  }, [seek]);

  // 播放进度百分比
  const progressPercent = duration > 0 ? (currentTime / duration) * 100 : 0;

  // 时间范围高亮
  const rangeStart = startTime != null && duration > 0 ? (startTime / duration) * 100 : undefined;
  const rangeEnd = endTime != null && duration > 0 ? (endTime / duration) * 100 : undefined;

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={960}
      centered
      destroyOnClose
      closable={false}
      bodyStyle={{ padding: 0, background: '#000', borderRadius: 12, overflow: 'hidden' }}
      style={{ top: 20 }}
    >
      <div ref={containerRef} style={{ position: 'relative', background: '#000' }}>
        {/* 标题栏 */}
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0, zIndex: 10,
          padding: '12px 16px',
          background: 'linear-gradient(to bottom, rgba(0,0,0,0.7), transparent)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <span style={{ color: '#e0e6ed', fontSize: 14, fontWeight: 500 }}>
            {title || '视频预览'}
          </span>
          <CloseOutlined
            onClick={onClose}
            style={{ color: '#a0aec0', cursor: 'pointer', fontSize: 16 }}
          />
        </div>

        {/* 视频区域 */}
        <video
          ref={videoRef}
          src={videoUrl(filePath)}
          preload="auto"
          onClick={togglePlay}
          playsInline
          style={{
            width: '100%', maxHeight: '70vh', display: 'block',
            cursor: 'pointer', background: '#000',
          }}
        />

        {/* 大播放按钮（暂停时显示） */}
        {!playing && (
          <div
            onClick={togglePlay}
            style={{
              position: 'absolute', inset: 0,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              cursor: 'pointer',
            }}
          >
            <div style={{
              width: 72, height: 72, borderRadius: '50%',
              background: `linear-gradient(135deg, ${CYAN}cc, ${PURPLE}cc)`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: `0 0 32px ${CYAN}44`,
              transition: 'transform 0.2s',
            }}>
              <PlayCircleOutlined style={{ fontSize: 36, color: '#fff', marginLeft: 4 }} />
            </div>
          </div>
        )}

        {/* 控制栏 */}
        <div style={{
          position: 'absolute', bottom: 0, left: 0, right: 0, zIndex: 10,
          background: 'linear-gradient(to top, rgba(0,0,0,0.85), transparent)',
          padding: '32px 16px 12px',
        }}>
          {/* 进度条 */}
          <div style={{ position: 'relative', marginBottom: 8 }}>
            {/* 时间范围高亮 */}
            {rangeStart != null && rangeEnd != null && (
              <div style={{
                position: 'absolute', top: 4, bottom: 4,
                left: `${rangeStart}%`, width: `${rangeEnd - rangeStart}%`,
                background: `${CYAN}22`, borderRadius: 2,
                pointerEvents: 'none',
              }} />
            )}
            <Slider
              min={0}
              max={duration || 100}
              step={0.1}
              value={currentTime}
              onChange={handleSliderChange}
              tooltip={{ formatter: (v) => formatTime(v ?? 0) }}
              styles={{
                track: { background: `linear-gradient(90deg, ${CYAN}, ${PURPLE})` },
                rail: { background: 'rgba(255,255,255,0.1)' },
                handle: { borderColor: CYAN },
              }}
            />
          </div>

          {/* 控制按钮 */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              {/* 后退5秒 */}
              <Tooltip title="后退 5 秒 (←)">
                <StepBackwardOutlined
                  onClick={() => skip(-5)}
                  style={{ color: '#c8d0dc', fontSize: 18, cursor: 'pointer' }}
                />
              </Tooltip>

              {/* 播放/暂停 */}
              {playing ? (
                <PauseCircleOutlined
                  onClick={togglePlay}
                  style={{ color: CYAN, fontSize: 28, cursor: 'pointer' }}
                />
              ) : (
                <PlayCircleOutlined
                  onClick={togglePlay}
                  style={{ color: CYAN, fontSize: 28, cursor: 'pointer' }}
                />
              )}

              {/* 前进5秒 */}
              <Tooltip title="前进 5 秒 (→)">
                <StepForwardOutlined
                  onClick={() => skip(5)}
                  style={{ color: '#c8d0dc', fontSize: 18, cursor: 'pointer' }}
                />
              </Tooltip>

              {/* 时间显示 */}
              <span style={{
                color: '#a0aec0', fontSize: 12,
                fontFamily: "'JetBrains Mono', monospace",
              }}>
                {formatTime(currentTime)} / {formatTime(duration)}
              </span>

              {/* 时间范围提示 */}
              {startTime != null && endTime != null && (
                <span style={{
                  color: CYAN, fontSize: 11, marginLeft: 4,
                  padding: '1px 8px', borderRadius: 4,
                  background: `${CYAN}11`, border: `1px solid ${CYAN}33`,
                }}>
                  片段 {formatTime(startTime)} - {formatTime(endTime)}
                </span>
              )}
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              {/* 播放速度 */}
              <Tooltip title="播放速度">
                <span
                  onClick={cyclePlaybackRate}
                  style={{
                    color: '#a0aec0', fontSize: 12, cursor: 'pointer',
                    fontFamily: "'JetBrains Mono', monospace",
                    padding: '2px 8px', borderRadius: 4,
                    border: '1px solid rgba(255,255,255,0.1)',
                  }}
                >
                  {playbackRate}x
                </span>
              </Tooltip>

              {/* 音量 */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                {muted || volume === 0 ? (
                  <MutedOutlined onClick={toggleMute} style={{ color: '#a0aec0', fontSize: 16, cursor: 'pointer' }} />
                ) : (
                  <SoundOutlined onClick={toggleMute} style={{ color: '#a0aec0', fontSize: 16, cursor: 'pointer' }} />
                )}
                <Slider
                  min={0}
                  max={1}
                  step={0.05}
                  value={muted ? 0 : volume}
                  onChange={changeVolume}
                  style={{ width: 60, margin: 0 }}
                  styles={{
                    track: { background: CYAN },
                    rail: { background: 'rgba(255,255,255,0.1)' },
                    handle: { borderColor: CYAN, width: 10, height: 10 },
                  }}
                />
              </div>

              {/* 全屏 */}
              <Tooltip title={fullscreen ? '退出全屏 (f)' : '全屏 (f)'}>
                {fullscreen ? (
                  <FullscreenExitOutlined onClick={toggleFullscreen} style={{ color: '#a0aec0', fontSize: 18, cursor: 'pointer' }} />
                ) : (
                  <FullscreenOutlined onClick={toggleFullscreen} style={{ color: '#a0aec0', fontSize: 18, cursor: 'pointer' }} />
                )}
              </Tooltip>
            </div>
          </div>
        </div>
      </div>
    </Modal>
  );
};

export default VideoPlayerModal;
