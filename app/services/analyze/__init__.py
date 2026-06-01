"""
视频分析服务包

架构（原 1365 行 manager.py 已拆分）：
    types.py        → 共享数据类型
    scoring.py      → 高光打分逻辑
    pipeline.py     → 子进程工作函数
    orchestrator.py → AnalysisManager 核心编排
    manager.py      → 向后兼容 re-export
"""

from .asr_service import ASRService, ASRResult, whisper_asr
from .emotion_service import EmotionService, EmotionAnalysis
from .visual_service import VisualService, VisualAnalysis
from .rhythm_service import RhythmService, RhythmAnalysis
from .speaker_diarization_service import SpeakerDiarizationService, DiarizationResult
from .types import AnalysisTask
from .manager import AnalysisManager, get_analysis_manager

__all__ = [
    "ASRService",
    "ASRResult",
    "whisper_asr",
    "EmotionService",
    "EmotionAnalysis",
    "VisualService",
    "VisualAnalysis",
    "RhythmService",
    "RhythmAnalysis",
    "SpeakerDiarizationService",
    "DiarizationResult",
    "AnalysisTask",
    "AnalysisManager",
    "get_analysis_manager",
]
