"""
剪辑流水线阶段实现
最终版：统一错误处理 + 配置支持
"""

import os
from typing import List, Dict, Any, Optional
from loguru import logger

from app.services.clip.modular_pipeline import (
    PipelineStage,
    PipelineContext,
    StageResult,
)
from app.services.clip.errors import StageError
from app.utils.ffmpeg import cut_segment, to_portrait, concat_videos
from app.utils.path_manager import get_path_manager


class SceneDetectionStage(PipelineStage):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or {}
        from app.services.highlight.scene_detect import SceneDetector
        self._detector = SceneDetector(
            threshold=self._config.get("threshold", 30),
            min_scene_len=self._config.get("min_scene_len", 2.0),
            max_scene_len=self._config.get("max_scene_len", 8.0),
        )

    @property
    def name(self) -> str:
        return "scene_detection"

    def execute(self, context: PipelineContext) -> StageResult:
        try:
            all_scenes = []
            for idx, video_path in enumerate(context.video_paths):
                ep_scenes = self._detector.detect(video_path, episode_index=idx + 1)
                for scene in ep_scenes:
                    all_scenes.append({
                        "video_path": scene.video_path,
                        "start_time": scene.start_time,
                        "end_time": scene.end_time,
                    })
            context.scenes = all_scenes
            return StageResult(True, f"检测到 {len(all_scenes)} 个场景")
        except Exception as e:
            raise StageError(self.name, str(e), e)


class HighlightScoringStage(PipelineStage):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or {}
        from app.services.highlight.scorer import HighlightScorer
        self._scorer = HighlightScorer(
            audio_weight=self._config.get("audio_weight", 0.35),
            emotion_weight=self._config.get("emotion_weight", 0.30),
            visual_weight=self._config.get("visual_weight", 0.20),
            rhythm_weight=self._config.get("rhythm_weight", 0.10),
        )
        self._path_mgr = get_path_manager()

    @property
    def name(self) -> str:
        return "highlight_scoring"

    def execute(self, context: PipelineContext) -> StageResult:
        scored = []
        temp_files = []
        try:
            for scene in context.scenes:
                temp_path = self._path_mgr.create_temp_file(suffix=".mp4", prefix="score_", delete_on_exit=True)
                temp_files.append(temp_path)

                cut_segment(
                    scene["video_path"],
                    str(temp_path),
                    scene["start_time"],
                    scene["end_time"] - scene["start_time"],
                    use_copy=False
                )

                scores = self._scorer.score(
                    str(temp_path),
                    duration=scene["end_time"] - scene["start_time"]
                )
                scores.update({
                    "video_path": scene["video_path"],
                    "start_time": scene["start_time"],
                    "end_time": scene["end_time"],
                })
                scored.append(scores)

            context.scored_segments = scored
            return StageResult(True, f"完成 {len(scored)} 个片段打分")
        except Exception as e:
            raise StageError(self.name, str(e), e)
        finally:
            for p in temp_files:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass


class HighlightSelectionStage(PipelineStage):
    """
    高光选择阶段（支持配置）
    """

    def __init__(self, target_duration: Optional[int] = None, config: Optional[Dict[str, Any]] = None):
        self.target_duration = target_duration
        self._config = config or {}

        from app.services.highlight.selector import HighlightSelector, HighlightSegment
        self._HighlightSegment = HighlightSegment
        self._selector = HighlightSelector(
            top_ratio=self._config.get("top_ratio", 0.4),
            min_segment_duration=self._config.get("min_segment_duration", 2.0),
            max_segments_per_episode=self._config.get("max_segments_per_episode", 10),
        )

    @property
    def name(self) -> str:
        return "highlight_selection"

    def execute(self, context: PipelineContext) -> StageResult:
        try:
            segments = []
            for s in context.scored_segments:
                seg = self._HighlightSegment(
                    video_path=s.get("video_path", ""),
                    start_time=s.get("start_time", 0.0),
                    end_time=s.get("end_time", 0.0),
                    score=s.get("total_score", 0.0),
                    audio_score=s.get("audio_score", 0.0),
                    emotion_score=s.get("emotion_score", 0.0),
                    visual_score=s.get("visual_score", 0.0),
                    rhythm_score=s.get("rhythm_score", 0.0),
                )
                segments.append(seg)

            selected = self._selector.select(segments, self.target_duration or context.target_duration)
            context.selected_segments = selected
            return StageResult(True, f"选中 {len(selected)} 个高光片段")
        except Exception as e:
            raise StageError(self.name, str(e), e)


class SegmentSortingStage(PipelineStage):
    @property
    def name(self) -> str:
        return "segment_sorting"

    def execute(self, context: PipelineContext) -> StageResult:
        try:
            from app.services.sorter.scene_sorter import SceneSorter, SortStrategy

            # 根据 narration_mode 选择最适合的排序策略（Phase 1 核心改动）
            mode = getattr(context, 'narration_mode', 'original')

            if mode == "original":
                # 原片解说：高燃为主，结合轻微情绪曲线（避免纯时间顺序导致情绪平铺）
                strategy = SortStrategy.EMOTION_CURVE
            elif mode == "hybrid":
                # 交叉解说：需要较强的情绪递进，让解说和原声更好地交替
                strategy = SortStrategy.EMOTION_CURVE
            elif mode == "full":
                # 全片解说：最需要完整的情绪弧线和故事感
                strategy = SortStrategy.EMOTION_CURVE
            else:
                strategy = SortStrategy.CHRONOLOGICAL

            sorter = SceneSorter(strategy=strategy)
            sorted_segments = sorter.sort(context.selected_segments)
            context.sorted_segments = sorted_segments

            logger.info(f"[SegmentSortingStage] 使用策略 {strategy.value} 进行排序（mode={mode}）")
            return StageResult(True, f"排序完成（策略: {strategy.value}）")
        except Exception as e:
            raise StageError(self.name, str(e), e)


class VideoCuttingStage(PipelineStage):
    """
    视频剪辑阶段（支持智能裁剪 smart_crop）

    支持两种裁剪模式：
    - simple: 使用简单的 to_portrait() 函数
    - smart: 使用 smart_crop() 函数，支持智能检测最佳裁剪位置
    """

    def __init__(self, crop_mode: str = "smart", target_ratio: str = "9:16"):
        """
        初始化视频剪辑阶段

        Args:
            crop_mode: 裁剪模式，"simple" 或 "smart"
            target_ratio: 目标比例，默认 "9:16"
        """
        self.crop_mode = crop_mode
        self.target_ratio = target_ratio

    @property
    def name(self) -> str:
        return "video_cutting"

    def execute(self, context: PipelineContext) -> StageResult:
        try:
            if not context.output_path:
                raise StageError(self.name, "缺少 output_path")

            # 如果 context 中有 target_ratio，覆盖默认值
            target_ratio = getattr(context, 'target_ratio', None) or self.target_ratio

            path_mgr = get_path_manager()
            temp_dir = path_mgr.create_temp_dir(prefix="cut_", delete_on_exit=True)

            cut_paths = []
            for i, seg in enumerate(context.sorted_segments):
                cut_path = os.path.join(temp_dir, f"cut_{i:03d}.mp4")
                
                # 智能 Jitter 避让台词与静音区首尾微调
                from app.utils.ffmpeg import get_safe_jittered_times
                start_time, end_time = get_safe_jittered_times(seg.video_path, seg.start_time, seg.end_time)
                duration = max(0.1, end_time - start_time)
                
                logger.info(f"片段 {i:03d} 首尾避让微调: {seg.start_time:.3f}s ~ {seg.end_time:.3f}s -> {start_time:.3f}s ~ {end_time:.3f}s (时长: {duration:.3f}s)")
                cut_segment(seg.video_path, cut_path, start_time, duration)
                cut_paths.append(cut_path)

            portrait_paths = []
            for i, cut_path in enumerate(cut_paths):
                portrait_path = os.path.join(temp_dir, f"portrait_{i:03d}.mp4")

                # 为每个独立切片生成唯一的微变速与视觉微调去重参数
                from app.utils.ffmpeg import generate_dedup_params
                dedup_p = generate_dedup_params()
                logger.info(f"片段 {i:03d} 独立去重微调参数: {dedup_p}")

                # 根据裁剪模式选择不同的裁剪方法
                if self.crop_mode == "smart":
                    # 智能裁剪：自动检测最佳裁剪位置，并叠加去重滤镜
                    from app.utils.ffmpeg import smart_crop
                    smart_crop(
                        cut_path,
                        portrait_path,
                        target_ratio=target_ratio,
                        crop_position="smart",
                        dedup_params=dedup_p
                    )
                else:
                    # 简单裁剪：居中裁剪，并叠加去重滤镜
                    to_portrait(cut_path, portrait_path, dedup_params=dedup_p)

                portrait_paths.append(portrait_path)

            concat_videos(portrait_paths, context.output_path)

            # 强化清理（M3）：使用更健壮的清理 + 记录失败
            cleanup_errors = []
            for p in cut_paths + portrait_paths:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError as e:
                        cleanup_errors.append(str(p))
                        logger.debug(f"临时文件清理失败（可忽略）: {p} - {e}")

            if cleanup_errors:
                logger.warning(f"[VideoCuttingStage] 部分临时文件清理失败: {len(cleanup_errors)} 个")

            logger.info(f"[VideoCuttingStage] 剪辑完成，使用 {self.crop_mode} 模式，目标比例 {target_ratio}")
            return StageResult(True, f"剪辑完成 ({self.crop_mode} 模式)", {"output_path": context.output_path})
        except Exception as e:
            raise StageError(self.name, str(e), e)
