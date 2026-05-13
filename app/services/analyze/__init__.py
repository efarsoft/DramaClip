"""
视频分析服务包（简化版）
"""

from .asr_service import ASRService, whisper_asr

__all__ = ["ASRService", "whisper_asr"]
