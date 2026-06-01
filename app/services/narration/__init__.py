"""
DramaClip - AI解说模式模块

AI解说模式的完整流水线：
LLM剧情解析 → 解说文案生成 → TTS语音合成 → 音画合成输出
"""

# 注意：只暴露主要的 NarrationPipeline，其他旧类已迁移/废弃
from .pipeline import NarrationPipeline

__all__ = [
    "NarrationPipeline",
]
