"""
DramaClip - 原片直剪模式模块

原片直剪模式的完整流水线：
保留原片全部音频，快速提取高光片段，拼接输出竖屏成片。
"""

from .pipeline import DirectCutPipeline

__all__ = ["DirectCutPipeline"]
