"""
DramaClip - AI解说模式模块

AI解说模式的完整流水线：
LLM剧情解析 → 解说文案生成 → TTS语音合成 → 音画合成输出
"""

from .pipeline import PlotParser, NarrationGenerator, TTSComposer, NarrationPipeline

__all__ = [
    "PlotParser",
    "NarrationGenerator", 
    "TTSComposer",
    "NarrationPipeline",
]
