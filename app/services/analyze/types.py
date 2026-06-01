"""
分析模块共享数据类型
包含 AnalysisTask dataclass、类型别名和配置辅助函数
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .asr_service import ASRResult
from .sensevoice_asr import SenseVoiceResult
from .emotion_service import EmotionAnalysis
from .visual_service import VisualAnalysis
from .rhythm_service import RhythmAnalysis
from .speaker_diarization_service import DiarizationResult

# 统一 ASR 结果类型
ASRResultUnion = Union[ASRResult, SenseVoiceResult]


def _get_asr_config() -> Dict[str, Any]:
    """从 UnifiedConfig 读取 ASR 配置（唯一入口）"""
    from app.config.unified_config import config
    return config.get_asr_config()


def _get_diarization_config() -> Dict[str, Any]:
    """从 UnifiedConfig 读取 Diarization 配置（支持 pyannote 选项）"""
    from app.config.unified_config import config
    return config.get_diarization_config()


@dataclass
class AnalysisTask:
    """分析任务"""
    task_id: str
    project_id: str
    video_id: str
    video_path: str
    status: str = "pending"
    progress: int = 0
    phase: str = ""
    message: str = ""
    asr_result: Optional[ASRResultUnion] = None
    emotion_result: Optional[EmotionAnalysis] = None
    visual_result: Optional[VisualAnalysis] = None
    rhythm_result: Optional[RhythmAnalysis] = None
    diarization_result: Optional[DiarizationResult] = None
    highlight_segments: List[Dict] = field(default_factory=list)
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    _temp_audio: Optional[Path] = field(default=None, init=False, repr=False)

    # Diarization 配置（支持 pyannote 精准模式）
    diarization_options: Dict[str, Any] = field(default_factory=dict)  # e.g. {"use_pyannote": true}
