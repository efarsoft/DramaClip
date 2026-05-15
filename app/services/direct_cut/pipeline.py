import logging
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
from pyscenetect import detect_scenes

from app.services.highlight.scorer import HighlightScorer
from app.services.highlight.selector import HighlightSelector, HighlightSegment
from app.services.sorter.scene_sorter import SceneSorter, SortStrategy
from app.utils.ffmpeg_utils import get_ffmpeg_path

logger = logging.getLogger(__name__)


class DirectCutPipeline:
    """原片直剪管道"""

    def __init__(
        self,
        config: Optional[Dict] = None,
    ):
        """
        初始化管道

        Args:
            config: 配置字典（从config.toml加载）
        """
        # 默认配置
        self.config = config or {}

        # 高光检测配置
        highlight_config = self.config.get("highlight", {})
        self.audio_weight = highlight_config.get("audio_weight", 0.4)
        self.emotion_weight = highlight_config.get("emotion_weight", 0.3)
        self.visual_weight = highlight_config.get("visual_weight", 0.2)
        self.rhythm_weight = highlight_config.get("rhythm_weight", 0.1)
        self.top_ratio = highlight_config.get("top_ratio", 0.3)
        self.min_segment_duration = highlight_config.get("min_segment_duration", 2.0)
        self.max_segments_per_episode = highlight_config.get(
            "max_segments_per_episode", 5
        )

        # 输出配置
        output_config = self.config.get("output", {})
        self.default_duration = output_config.get("default_duration", 30)
        self.resolution = output_config.get("resolution", "1080P")
        self.aspect_ratio = output_config.get("aspect_ratio", "9:16")
        self.fps = output_config.get("fps", 25)

        # 场景检测配置
        scene_config = self.config.get("scene_detect", {})
        self.scene_threshold = scene_config.get("threshold", 30)
        self.min_scene_len = scene_config.get("min_scene_len", 2)
        self.max_scene_len = scene_config.get("max_scene_len", 8)

        # 初始化子模块
        self.scorer = HighlightScorer(
            audio_weight=self.audio_weight,
            emotion_weight=self.emotion_weight,
            visual_weight=self.visual_weight,
            rhythm_weight=self.rhythm_weight,
            plot_importance_weight=0.15,  # 剧情重要性权重 15%
        )
        self.selector = HighlightSelector(
            top_ratio=self.top_ratio,
            min_segment_duration=self.min_segment_duration,
            max_segments_per_episode=self.max_segments_per_episode,
        )
        self.sorter = SceneSorter(strategy=SortStrategy.CHRONOLOGICAL)

        logger.info("DirectCutPipeline initialized")

    def run_segments_only(
        self, video_paths: List[str], target_duration: Optional[int] = None
    ) -> List['HighlightSegment']:
        """
        仅执行片段选择（不输出视频），返回排序后的高光片段列表。
        供解说管线复用：先选片段 → 基于片段生成解说 → 精确对齐剪辑+混合。
        """
        scenes = self._detect_scenes(video_paths)
        scored_segments = self._score_scenes(scenes)
        selected_segments = self._select_highlights(scored_segments, target_duration)
        sorted_segments = self._sort_segments(selected_segments)
        return sorted_segments

    def run(
        self,
        video_paths: List[str],
        output_path: Optional[str] = None,
        target_duration: Optional[int] = None,
    ) -> str:
        """
        执行完整的原片直剪流水线

        Args:
            video_paths: 输入视频路径列表（多集）
            output_path: 输出文件路径（可选，默认自动生成）
            target_duration: 目标时长（秒，可选，默认使用配置）

        Returns:
            输出文件路径
        """
        if not video_paths:
            raise ValueError("No video paths provided")

        logger.info(f"Starting DirectCutPipeline with {len(video_paths)} videos")
        if target_duration:
            logger.info(f"Target duration: {target_duration}s")
        # 1. 场景检测
        logger.info("Step 1: Scene detection")
        scenes = self._detect_scenes(video_paths)

        # 2. 高光打分
        logger.info("Step 2: Highlight scoring")
        scored_segments = self._score_scenes(scenes)

        # 3. 高光选择
        logger.info("Step 3: Highlight selection")
        selected_segments = self._select_highlights(
            scored_segments, target_duration
        )

        # 4. 智能排序
        logger.info("Step 4: Intelligent sorting")
        sorted_segments = self._sort_segments(selected_segments)

        # 5. 视频剪辑和拼接
        logger.info("Step 5: Video cutting and concatenation")
        if output_path is None:
            output_path = self._generate_output_path(video_paths[0])

        final_path = self._cut_and_concat(sorted_segments, output_path)

        logger.info(f"Pipeline completed: {final_path}")
        return final_path

    def _detect_scenes(
        self, video_paths: List[str]
    ) -> List[Tuple[str, float, float]]:
        """
        场景检测

        Args:
            video_paths: 视频路径列表

        Returns:
            [(video_path, start_time, end_time), ...]
        """
        scenes = []

        for video_path in video_paths:
            logger.info(f"Detecting scenes in: {video_path}")

            try:
                # 使用PySceneDetect检测场景
                scene_list = detect_scenes(
                    video_path, threshold=self.scene_threshold
                )

                # 转换为(start_time, end_time)列表
                for scene in scene_list:
                    start_time = scene[0].get_seconds()
                    end_time = scene[1].get_seconds()

                    # 过滤太短或太长的场景
                    duration = end_time - start_time
                    if duration < self.min_scene_len:
                        continue
                    if duration > self.max_scene_len:
                        # 截断到最大长度
                        end_time = start_time + self.max_scene_len
                        duration = self.max_scene_len

                    scenes.append((video_path, start_time, end_time))

                logger.info(
                    f"Detected {len(scene_list)} scenes in {video_path}"
                )

            except Exception as e:
                logger.error(f"Error detecting scenes in {video_path}: {e}")
                # 降级：将整个视频作为一个场景
                cap = cv2.VideoCapture(video_path)
                if cap.isOpened():
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    duration = frame_count / fps if fps > 0 else 0
                    cap.release()
                    scenes.append((video_path, 0.0, duration))
                else:
                    logger.warning(f"Cannot open video: {video_path}")

        logger.info(f"Total scenes detected: {len(scenes)}")
        return scenes

    def _score_scenes(
        self, scenes: List[Tuple[str, float, float]]
    ) -> List[Dict]:
        """
        对场景进行高光打分

        Args:
            scenes: [(video_path, start_time, end_time), ...]

        Returns:
            打分结果列表，每个元素包含各维度分数
        """
        scored = []

        for video_path, start_time, end_time in scenes:
            # 提取场景片段（临时文件）
            temp_path = self._extract_scene(video_path, start_time, end_time)

            try:
                # 打分
                score_dict = self.scorer.score(temp_path)
                # 嵌入场景元数据，用于后续重建HighlightSegment
                score_dict["video_path"] = video_path
                score_dict["start_time"] = start_time
                score_dict["end_time"] = end_time
                scored.append(score_dict)
            finally:
                # 清理临时文件
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        return scored

    def _extract_scene(
        self, video_path: str, start_time: float, end_time: float
    ) -> str:
        """
        提取场景片段为临时文件

        Returns:
            临时文件路径
        """
        temp_dir = tempfile.gettempdir()
        # 使用 uuid 防止并发冲突
        temp_path = os.path.join(temp_dir, f"scene_{uuid.uuid4().hex[:8]}_{start_time:.1f}_{end_time:.1f}.mp4")

        # 使用重编码而非 -c copy，确保输出文件可被 cv2/librosa 正确读取
        # -c copy 在非关键帧对齐时会输出损坏的 MP4
        cmd = [
            get_ffmpeg_path(),
            "-y",
            "-ss", str(start_time),       # 放在 -i 前实现快速 seek
            "-i", video_path,
            "-t", str(end_time - start_time),
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            temp_path,
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True)
            return temp_path
        except subprocess.CalledProcessError as e:
            logger.error(f"Error extracting scene: {e}")
            raise

    def _select_highlights(
        self,
        scored_segments: List[Dict],
        target_duration: Optional[int] = None,
    ) -> List[HighlightSegment]:
        """
        选择高光片段

        Args:
            scored_segments: 打分结果列表
            target_duration: 目标时长（秒）

        Returns:
            选中的高光片段列表
        """
        # 构建HighlightSegment对象列表
        segments = []
        for score_dict in scored_segments:
            seg = HighlightSegment(
                video_path=score_dict.get("video_path", ""),
                start_time=score_dict.get("start_time", 0.0),
                end_time=score_dict.get("end_time", 0.0),
                score=score_dict.get("total_score", 0.0),
                audio_score=score_dict.get("audio_score", 0.0),
                emotion_score=score_dict.get("emotion_score", 0.0),
                visual_score=score_dict.get("visual_score", 0.0),
                rhythm_score=score_dict.get("rhythm_score", 0.0),
            )
            segments.append(seg)

        # 调用selector
        return self.selector.select(segments, target_duration)

    def _sort_segments(
        self, segments: List[HighlightSegment]
    ) -> List[HighlightSegment]:
        """
        智能排序

        Args:
            segments: 高光片段列表

        Returns:
            排序后的高光片段列表
        """
        return self.sorter.sort(segments)

    def _cut_and_concat(
        self, segments: List[HighlightSegment], output_path: str
    ) -> str:
        """
        视频剪辑和拼接

        Args:
            segments: 排序后的高光片段列表
            output_path: 输出文件路径

        Returns:
            输出文件路径
        """
        # 1. 切割每个片段
        temp_dir = tempfile.gettempdir()
        cut_paths = []
        for i, seg in enumerate(segments):
            cut_path = os.path.join(temp_dir, f"cut_{i:03d}.mp4")
            self._cut_segment(seg, cut_path)
            cut_paths.append(cut_path)

        # 2. 转换为竖屏（9:16）
        portrait_paths = []
        for i, cut_path in enumerate(cut_paths):
            portrait_path = os.path.join(temp_dir, f"portrait_{i:03d}.mp4")
            self._to_portrait(cut_path, portrait_path)
            portrait_paths.append(portrait_path)

        # 3. 拼接所有片段
        self._concat_videos(portrait_paths, output_path)

        # 4. 清理临时文件
        for path in cut_paths + portrait_paths:
            if os.path.exists(path):
                os.remove(path)

        logger.info(f"Video saved to: {output_path}")
        return output_path

    def _cut_segment(self, seg: HighlightSegment, output_path: str):
        """切割视频片段 — 使用重编码确保输出完整"""
        cmd = [
            get_ffmpeg_path(),
            "-y",
            "-ss", str(seg.start_time),       # -ss 放 -i 前做快速 seek
            "-i", seg.video_path,
            "-t", str(seg.duration),
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            output_path,
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Error cutting segment: {e}")
            raise

    def _to_portrait(self, input_path: str, output_path: str):
        """
        横屏转竖屏（9:16）

        策略：
        1. 检测视频宽高比，如果已经是 9:16 竖屏则直接复制
        2. 否则居中裁剪到 9:16
        """
        # 检测视频宽高
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            logger.warning(f"Cannot open video for aspect check: {input_path}, skipping portrait conversion")
            import shutil
            shutil.copy2(input_path, output_path)
            return

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        # 计算当前宽高比
        aspect = width / height if height > 0 else 1.0
        target_aspect = 9.0 / 16.0  # ≈ 0.5625

        # 如果宽高比接近 9:16（±10%），直接复制不重编码
        if abs(aspect - target_aspect) < 0.06:
            logger.info(f"Video already near 9:16 (aspect={aspect:.3f}), copying as-is")
            import shutil
            shutil.copy2(input_path, output_path)
            return

        # 横屏转竖屏：居中裁剪到 9:16
        cmd = [
            get_ffmpeg_path(),
            "-y",
            "-i", input_path,
            "-vf", "crop=in_h*9/16:in_h:(in_w-in_h*9/16)/2:0",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "copy",
            output_path,
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Error converting to portrait: {e}")
            raise

    def _concat_videos(self, video_paths: List[str], output_path: str):
        """
        拼接多个视频片段

        Args:
            video_paths: 视频片段路径列表
            output_path: 输出文件路径
        """
        if len(video_paths) == 0:
            raise ValueError("No video paths to concatenate")
        if len(video_paths) == 1:
            # 单片段，直接复制
            import shutil
            shutil.copy2(video_paths[0], output_path)
            return

        # 创建临时列表文件（用 uuid 防止并发冲突）
        temp_dir = tempfile.gettempdir()
        list_file = os.path.join(temp_dir, f"concat_{uuid.uuid4().hex[:8]}.txt")
        # ffmpeg concat 需要正斜杠路径
        with open(list_file, "w") as f:
            for path in video_paths:
                escaped = path.replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")

        # 先尝试 concat + stream copy（最快）
        # 如果片段编码参数不一致，会失败，此时降级到重编码
        cmd_copy = [
            get_ffmpeg_path(),
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            output_path,
        ]

        try:
            result = subprocess.run(cmd_copy, check=True, capture_output=True, text=True)
            logger.info("Concatenated with stream copy (fast)")
        except subprocess.CalledProcessError:
            # 降级：concat + 重编码（兼容不同编码参数的片段）
            logger.warning("Stream copy concat failed, falling back to re-encode")
            cmd_reencode = [
                get_ffmpeg_path(),
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", list_file,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                output_path,
            ]
            try:
                subprocess.run(cmd_reencode, check=True, capture_output=True, text=True)
                logger.info("Concatenated with re-encode (compatible)")
            except subprocess.CalledProcessError as e:
                logger.error(f"Error concatenating videos (re-encode): {e.stderr}")
                raise
        finally:
            if os.path.exists(list_file):
                os.remove(list_file)

    def _generate_output_path(self, reference_path: str) -> str:
        """生成默认输出路径"""
        base_dir = os.path.dirname(reference_path)
        timestamp = uuid.uuid4().hex[:8]
        return os.path.join(base_dir, f"dramaclip_output_{timestamp}.mp4")

    def set_sort_strategy(self, strategy: SortStrategy):
        """设置排序策略"""
        self.sorter.set_strategy(strategy)
