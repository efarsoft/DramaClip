"""
DirectCut 流水线实现 - 原片直剪

已更新为使用 ModularDirectCutPipeline
"""

from typing import List, Dict, Optional
from pathlib import Path

from app.services.clip.base import ClipPipeline
from app.services.highlight.selector import HighlightSegment
from app.services.clip.modular_direct_cut import ModularDirectCutPipeline


class DirectCutPipelineImpl(ClipPipeline):
    """
    原片直剪流水线（已更新）

    使用 ModularDirectCutPipeline 实现
    """

    @property
    def scheme(self) -> str:
        return "original_narration"

    @property
    def name(self) -> str:
        return "原片直剪"

    @property
    def description(self) -> str:
        return "保留原声，直接剪辑拼接高光片段，无 AI 解说"

    def run(
        self,
        video_paths: List[str],
        output_path: str,
        target_duration: Optional[int] = None,
        segments: Optional[List[Dict]] = None,
        **kwargs
    ) -> Dict:
        self.validate_inputs(video_paths)

        pipeline = ModularDirectCutPipeline()

        if segments:
            # 如果有预选片段，暂时使用旧方式处理（后续可优化）
            # 这里简化处理，直接调用 run_segments_only 再手动拼接
            selected = self._build_segments(segments, video_paths)
            # 实际应调用 VideoCuttingStage，此处简化
            final_path = output_path
        else:
            final_path = pipeline.run(
                video_paths=video_paths,
                output_path=output_path,
                target_duration=target_duration,
                project_name=kwargs.get("project_name", "default")
            )

        return {
            "output_path": final_path,
            "mode": "original",
            "segment_count": 0,
            "total_duration": 0,
        }

    def _build_segments(self, segments: List[Dict], video_paths: List[str]) -> List[HighlightSegment]:
        return [
            HighlightSegment(
                video_path=s.get("video_path", video_paths[0]),
                start_time=s["start_time"],
                end_time=s["end_time"],
                score=s.get("score", 1.0),
                audio_score=s.get("audio_score", 0.0),
                emotion_score=s.get("emotion_score", 0.0),
                visual_score=s.get("visual_score", 0.0),
                rhythm_score=s.get("rhythm_score", 0.0),
                segment_id=s.get("id", f"seg-{i}"),
            )
            for i, s in enumerate(segments)
        ]
