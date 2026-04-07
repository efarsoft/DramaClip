"""
DramaClip - 高光识别与筛选模块

多维度高光打分引擎，包含四个子评分器和统一筛选逻辑：
- scorer: 多维度打分引擎（综合调度）
- audio_scorer: 音频爆点分析（librosa）
- emotion_scorer: 台词情绪分析（NLP关键词）
- visual_scorer: 画面特征分析（OpenCV人脸/动作）
- rhythm_scorer: 镜头节奏分析
- selector: 高光筛选器（Top-N + 剧集均衡）
- scene_detect: PySceneDetect 镜头分割
"""

from .scorer import HighlightScorer, ScoringResult
from .audio_scorer import AudioScorer
from .emotion_scorer import EmotionScorer
from .visual_scorer import VisualScorer
from .rhythm_scorer import RhythmScorer
from .selector import HighlightSelector
from .scene_detect import SceneDetector, SceneInfo, detect_all_episodes

__all__ = [
    "HighlightScorer", "ScoringResult",
    "AudioScorer", "EmotionScorer", "VisualScorer", "RhythmScorer",
    "HighlightSelector",
    "SceneDetector", "SceneInfo", "detect_all_episodes",
]
