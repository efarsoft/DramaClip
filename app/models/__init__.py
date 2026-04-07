"""
DramaClip - 数据模型包

提供项目中所有 Pydantic 数据模型的统一导出。
"""

from app.models.schema import (
    # 原有模型
    VideoAspect,
    VideoConcatMode,
    SubtitlePosition,
    AudioVolumeDefaults,
    AudioVolumeConfig,
    MaterialInfo,
    VideoClipParams,
    
    # DramaClip 新增模型
    ClipMode,
    SceneSegment,
    HighlightScoreWeights,
    HighlightConfig,
    DramaClipOutputConfig,
    NarrationScript,
    EpisodeInput,
)

__all__ = [
    # 原有模型
    "VideoAspect",
    "VideoConcatMode", 
    "SubtitlePosition",
    "AudioVolumeDefaults",
    "AudioVolumeConfig",
    "MaterialInfo",
    "VideoClipParams",
    
    # DramaClip 新增模型
    "ClipMode",
    "SceneSegment",
    "HighlightScoreWeights",
    "HighlightConfig",
    "DramaClipOutputConfig",
    "NarrationScript",
    "EpisodeInput",
]
