"""
pyscenetect - 场景检测模块兼容层
包装 PySceneDetect (scenedetect) 提供简洁的 API

Usage:
    from pyscenetect import detect_scenes
    scenes = detect_scenes("video.mp4", threshold=30.0)
"""

import logging
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# 尝试导入真正的 PySceneDetect
try:
    from scenedetect import detect as scenedetect_detect, ContentDetector
    HAS_SCENEDETECT = True
except ImportError:
    HAS_SCENEDETECT = False
    logger.warning("PySceneDetect (scenedetect) not installed. Using fallback scene detection.")


def detect_scenes(
    video_path: str,
    threshold: float = 30.0,
    min_scene_len: float = 1.0,
) -> List[Tuple]:
    """
    检测视频中的场景切换

    Args:
        video_path: 视频文件路径
        threshold: 场景检测阈值 (越低越敏感)
        min_scene_len: 最小场景长度（秒）

    Returns:
        [(start_timecode, end_timecode), ...]
        每个 timecode 有 .get_seconds() 方法
    """
    if HAS_SCENEDETECT:
        return _detect_with_scenedetect(video_path, threshold, min_scene_len)
    else:
        return _detect_fallback(video_path, min_scene_len)


def _detect_with_scenedetect(
    video_path: str,
    threshold: float,
    min_scene_len: float,
) -> List[Tuple]:
    """使用 PySceneDetect 检测"""
    from scenedetect import open_video, SceneManager
    from scenedetect.detectors import ContentDetector

    video = open_video(video_path)
    scene_manager = SceneManager()
    scene_manager.add_detector(
        ContentDetector(threshold=threshold, min_scene_len=min_scene_len)
    )
    scene_manager.detect_scenes(video)
    return scene_manager.get_scene_list()


def _detect_fallback(
    video_path: str,
    min_scene_len: float = 1.0,
) -> List[Tuple]:
    """降级方案：无场景检测依赖时使用 OpenCV 简单检测"""
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.warning(f"Cannot open video: {video_path}")
        return []

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 25.0

    scenes = []
    prev_hist = None
    scene_start = 0.0
    frame_idx = 0
    min_frames = int(min_scene_len * fps)

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # 每 10 帧检测一次（提高性能）
        if frame_idx % 10 != 0:
            frame_idx += 1
            continue

        # 计算 HSV 直方图
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
        cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)

        if prev_hist is not None:
            # 计算直方图差异
            diff = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CHISQR)
            current_time = frame_idx / fps

            if diff > 50.0:  # 场景切换
                duration = current_time - scene_start
                if duration >= min_scene_len:
                    # 返回的 timecode 对象兼容 scenedetect 接口
                    scenes.append((
                        _Timecode(scene_start, fps),
                        _Timecode(current_time, fps),
                    ))
                scene_start = current_time

        prev_hist = hist
        frame_idx += 1

    cap.release()

    # 最后一个场景
    if frame_idx > 0:
        total_duration = frame_idx / fps
        if total_duration - scene_start >= min_scene_len:
            scenes.append((
                _Timecode(scene_start, fps),
                _Timecode(total_duration, fps),
            ))

    if not scenes:
        # 没有检测到场景切换，整个视频作为一个场景
        total_duration = frame_idx / fps
        scenes.append((
            _Timecode(0.0, fps),
            _Timecode(total_duration, fps),
        ))

    logger.info(
        f"Fallback detector: {len(scenes)} scenes in {video_path}"
    )
    return scenes


class _Timecode:
    """兼容 PySceneDetect Timecode 接口的简单实现"""

    def __init__(self, seconds: float, fps: float = 25.0):
        self._seconds = seconds
        self._framerate = fps

    def get_seconds(self) -> float:
        return self._seconds

    def get_frames(self) -> int:
        return int(self._seconds * self._framerate)

    def get_timecode(self) -> str:
        h = int(self._seconds // 3600)
        m = int((self._seconds % 3600) // 60)
        s = int(self._seconds % 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def __sub__(self, other):
        return self._seconds - other._seconds

    def __gt__(self, other):
        return self._seconds > other._seconds

    def __lt__(self, other):
        return self._seconds < other._seconds

    def __eq__(self, other):
        return self._seconds == other._seconds

    def __repr__(self):
        return f"_Timecode({self.get_timecode()})"
