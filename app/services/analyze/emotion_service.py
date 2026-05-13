"""
情绪分析服务
基于文本和音频特征进行情绪识别
"""

import json
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class EmotionPoint:
    """情绪数据点"""
    timestamp: float
    emotion: str          # anger/disgust/fear/joy/sadness/surprise/neutral
    intensity: float      # 0.0 - 1.0
    confidence: float


@dataclass
class EmotionAnalysis:
    """情绪分析结果"""
    video_id: str
    overall_emotion: str
    emotion_curve: List[EmotionPoint] = field(default_factory=list)
    emotion_distribution: Dict[str, float] = field(default_factory=dict)
    peak_moments: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "video_id": self.video_id,
            "overall_emotion": self.overall_emotion,
            "emotion_curve": [
                {"timestamp": p.timestamp, "emotion": p.emotion, "intensity": p.intensity}
                for p in self.emotion_curve
            ],
            "emotion_distribution": self.emotion_distribution,
            "peak_moments": self.peak_moments,
        }


class EmotionService:
    """
    情绪分析服务
    支持基于文本和音频特征的情绪识别
    """

    # 情绪关键词映射
    EMOTION_KEYWORDS = {
        "joy": ["开心", "高兴", "快乐", "笑", "哈哈", "欢呼", "太棒了", "完美", "好"],
        "sadness": ["难过", "伤心", "哭", "痛苦", "悲伤", "失落", "遗憾", "可惜"],
        "anger": ["生气", "愤怒", "可恶", "混蛋", "该死", "气死我了", "滚"],
        "fear": ["害怕", "恐惧", "担心", "紧张", "害怕", "惊恐"],
        "surprise": ["惊讶", "吃惊", "意外", "震惊", "想不到", "天哪"],
        "disgust": ["恶心", "讨厌", "嫌弃", "厌恶", "反感"],
    }

    # 情绪颜色映射（用于图表）
    EMOTION_COLORS = {
        "joy": "#FFD700",
        "sadness": "#4169E1",
        "anger": "#FF4500",
        "fear": "#8B008B",
        "surprise": "#FF69B4",
        "disgust": "#9ACD32",
        "neutral": "#808080",
    }

    def __init__(self, use_api: bool = False, api_key: str = ""):
        self.use_api = use_api
        self.api_key = api_key
        self._cancel_flag = False

    def cancel(self):
        """取消分析"""
        self._cancel_flag = True

    def analyze(
        self,
        text_segments: List[Dict],
        video_id: str,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> EmotionAnalysis:
        """
        分析情绪

        Args:
            text_segments: 文本片段列表 [{start, end, text}]
            video_id: 视频 ID
            progress_callback: 进度回调

        Returns:
            EmotionAnalysis 情绪分析结果
        """
        self._cancel_flag = False
        emotion_curve: List[EmotionPoint] = []
        emotion_counts: Dict[str, int] = {}

        total = len(text_segments)
        for i, seg in enumerate(text_segments):
            if self._cancel_flag:
                raise InterruptedError("Analysis cancelled")

            # 分析每段文本的情绪
            emotion, intensity = self._analyze_text_emotion(seg.get("text", ""))

            point = EmotionPoint(
                timestamp=seg.get("start", 0),
                emotion=emotion,
                intensity=intensity,
                confidence=0.8,
            )
            emotion_curve.append(point)
            emotion_counts[emotion] = emotion_counts.get(emotion, 0) + 1

            if progress_callback and i % 5 == 0:
                progress = int((i / total) * 100)
                progress_callback(progress, f"已分析 {i}/{total} 段...")

        # 计算整体情绪
        if emotion_counts:
            overall = max(emotion_counts, key=emotion_counts.get)
        else:
            overall = "neutral"

        # 计算情绪分布（百分比）
        total_count = sum(emotion_counts.values())
        emotion_distribution = {
            e: (c / total_count * 100) if total_count > 0 else 0
            for e, c in emotion_counts.items()
        }

        # 找出情绪高峰
        peak_moments = self._find_peak_moments(emotion_curve)

        return EmotionAnalysis(
            video_id=video_id,
            overall_emotion=overall,
            emotion_curve=emotion_curve,
            emotion_distribution=emotion_distribution,
            peak_moments=peak_moments,
        )

    def _analyze_text_emotion(self, text: str) -> tuple[str, float]:
        """分析文本情绪"""
        if not text:
            return "neutral", 0.0

        text = text.lower()
        scores: Dict[str, float] = {}

        for emotion, keywords in self.EMOTION_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scores[emotion] = score

        if not scores:
            return "neutral", 0.3

        # 返回最高分的情绪
        top_emotion = max(scores, key=scores.get)
        intensity = min(1.0, scores[top_emotion] * 0.2 + 0.5)
        return top_emotion, intensity

    def _find_peak_moments(self, curve: List[EmotionPoint]) -> List[Dict]:
        """找出情绪高峰时刻"""
        peaks = []
        for point in curve:
            if point.intensity > 0.7 and point.emotion in ["joy", "anger", "surprise"]:
                peaks.append({
                    "timestamp": point.timestamp,
                    "emotion": point.emotion,
                    "intensity": point.intensity,
                })
        return peaks[:10]  # 最多返回 10 个

    def save_result(self, result: EmotionAnalysis, output_path: Path):
        """保存分析结果"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        logger.info(f"Saved emotion analysis to {output_path}")

    @staticmethod
    def load_result(video_id: str, project_path: Path) -> Optional[EmotionAnalysis]:
        """加载分析结果"""
        result_file = project_path / "analysis" / f"{video_id}_emotion.json"
        if not result_file.exists():
            return None
        try:
            data = json.loads(result_file.read_text(encoding="utf-8"))
            curve = [EmotionPoint(**p) for p in data["emotion_curve"]]
            return EmotionAnalysis(
                video_id=data["video_id"],
                overall_emotion=data["overall_emotion"],
                emotion_curve=curve,
                emotion_distribution=data["emotion_distribution"],
                peak_moments=data["peak_moments"],
            )
        except Exception as e:
            logger.error(f"Failed to load emotion result: {e}")
            return None

    @staticmethod
    def get_emotion_color(emotion: str) -> str:
        """获取情绪对应的颜色"""
        return EmotionService.EMOTION_COLORS.get(emotion, "#808080")

    @staticmethod
    def get_emotion_label(emotion: str) -> str:
        """获取情绪对应的中文标签"""
        labels = {
            "joy": "喜悦",
            "sadness": "悲伤",
            "anger": "愤怒",
            "fear": "恐惧",
            "surprise": "惊讶",
            "disgust": "厌恶",
            "neutral": "中性",
        }
        return labels.get(emotion, emotion)
