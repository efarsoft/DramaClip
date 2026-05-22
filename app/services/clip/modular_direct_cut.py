"""
模块化原片直剪流水线（最终优化版）
支持配置、进度回调、错误处理、资源清理
"""

from typing import List, Optional, Dict, Any, Callable
from loguru import logger

from app.services.clip.modular_pipeline import ModularPipeline, PipelineContext
from app.services.clip.stages import (
    SceneDetectionStage,
    HighlightScoringStage,
    HighlightSelectionStage,
    SegmentSortingStage,
    VideoCuttingStage,
)
from app.config.unified_config import config as app_config


class ModularDirectCutPipeline:
    """
    模块化原片直剪流水线
    已支持配置系统、进度回调、错误处理
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or self._load_default_config()

    def _load_default_config(self) -> Dict[str, Any]:
        """从全局配置加载"""
        try:
            scene_config = app_config.get("scene_detect", {})
            highlight_config = app_config.get("highlight", {})
            return {
                "scene_detect": {
                    "threshold": scene_config.get("threshold", 30),
                    "min_scene_len": scene_config.get("min_scene_len", 2.0),
                    "max_scene_len": scene_config.get("max_scene_len", 8.0),
                },
                "highlight": {
                    "audio_weight": highlight_config.get("audio_weight", 0.35),
                    "emotion_weight": highlight_config.get("emotion_weight", 0.30),
                    "visual_weight": highlight_config.get("visual_weight", 0.20),
                    "rhythm_weight": highlight_config.get("rhythm_weight", 0.10),
                }
            }
        except Exception:
            logger.warning("加载配置失败，使用默认值")
            return {}

    def run(
        self,
        video_paths: List[str],
        output_path: str,
        target_duration: Optional[int] = None,
        project_name: str = "default",
        progress_callback: Optional[Callable] = None,
        crop_mode: str = "smart",
        target_ratio: str = "9:16",
    ) -> str:
        pipeline = ModularPipeline()

        pipeline.add_stage(SceneDetectionStage(self.config.get("scene_detect")))
        pipeline.add_stage(HighlightScoringStage(self.config.get("highlight")))
        pipeline.add_stage(HighlightSelectionStage(target_duration=target_duration))
        pipeline.add_stage(SegmentSortingStage())
        pipeline.add_stage(VideoCuttingStage(crop_mode=crop_mode, target_ratio=target_ratio))

        context = PipelineContext(
            video_paths=video_paths,
            target_duration=target_duration,
            project_name=project_name,
            output_path=output_path,
            target_ratio=target_ratio,
        )

        if progress_callback:
            pipeline.set_progress_callback(progress_callback)

        try:
            result = pipeline.run(context)
            return result.output_path or output_path
        except Exception as e:
            logger.error(f"ModularDirectCutPipeline 执行失败: {e}")
            raise

    def run_segments_only(
        self,
        video_paths: List[str],
        target_duration: Optional[int] = None,
    ) -> List[Any]:
        pipeline = ModularPipeline()
        pipeline.add_stage(SceneDetectionStage(self.config.get("scene_detect")))
        pipeline.add_stage(HighlightScoringStage(self.config.get("highlight")))
        pipeline.add_stage(HighlightSelectionStage(target_duration=target_duration))

        context = PipelineContext(
            video_paths=video_paths,
            target_duration=target_duration,
        )

        result = pipeline.run(context)
        return result.selected_segments
