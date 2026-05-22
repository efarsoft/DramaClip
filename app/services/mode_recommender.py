"""
智能剪辑模式推荐模块
P0核心功能：根据视频内容分析自动推荐最佳剪辑模式

核心功能：
1. 基于视频类型推荐剪辑模式
2. 分析剧集特征（悬疑/爱情/恐怖/喜剧等）
3. 推荐最佳输出比例（9:16/16:9）
4. 一键智能模式（自动选择）
"""

import re
from enum import Enum
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Callable
from loguru import logger

from app.services.analyze.asr_service import ASRService


class ClipMode(str, Enum):
    """剪辑模式"""
    ORIGINAL = "original"           # 原片直剪
    HYBRID = "hybrid"              # 混合解说
    FULL_NARRATION = "full"        # 全解说
    ALL_THREE = "all_three"        # 一键三连


class VideoGenre(str, Enum):
    """视频类型"""
    SUSPENSE = "suspense"         # 悬疑剧
    HORROR = "horror"             # 恐怖片
    ROMANCE = "romance"           # 爱情剧
    ACTION = "action"             # 动作片
    COMEDY = "comedy"            # 喜剧
    DOCUMENTARY = "documentary"    # 纪录片
    DRAMA = "drama"             # 剧情片
    THRILLER = "thriller"       # 惊悚片
    UNKNOWN = "unknown"          # 未知


@dataclass
class ModeRecommendation:
    """模式推荐结果"""
    recommended_mode: ClipMode
    confidence: float           # 置信度 0-1
    reasons: List[str]         # 推荐理由
    alternatives: List[ClipMode]  # 备选模式
    suggested_ratio: str       # 推荐比例 "9:16" | "16:9"
    target_duration: Optional[int]  # 建议时长（秒）
    auto_title_enabled: bool   # 是否建议开启AI标题


@dataclass
class VideoAnalysis:
    """视频分析结果"""
    video_count: int
    total_duration: float
    has_subtitles: bool
    subtitle_languages: List[str]
    estimated_dialogue_ratio: float  # 对话占比 0-1
    detected_genre: VideoGenre
    content_features: Dict[str, float]  # 内容特征
    audio_features: Dict[str, float]   # 音频特征


class SmartModeRecommender:
    """
    智能模式推荐器
    """

    def __init__(self):
        self._genre_keywords = {
            VideoGenre.SUSPENSE: [
                "悬疑", "推理", "破案", "凶杀", "谜案", "犯罪",
                "反转", "真相", "秘密", "阴谋"
            ],
            VideoGenre.HORROR: [
                "恐怖", "惊悚", "鬼片", "灵异", "丧尸", "血腥",
                "惊吓", "噩梦", "黑暗"
            ],
            VideoGenre.ROMANCE: [
                "爱情", "甜蜜", "虐恋", "甜宠", "浪漫", "恋人",
                "心动", "告白", "婚姻", "前任"
            ],
            VideoGenre.ACTION: [
                "动作", "打斗", "武侠", "功夫", "格斗", "枪战",
                "爆炸", "追逐", "特种兵"
            ],
            VideoGenre.COMEDY: [
                "喜剧", "搞笑", "幽默", "段子", "爆笑", "欢乐",
                "小品", "综艺"
            ],
            VideoGenre.DOCUMENTARY: [
                "纪录", "真实", "访谈", "科普", "自然", "历史",
                "社会", "人物"
            ],
            VideoGenre.DRAMA: [
                "剧情", "人生", "家庭", "励志", "温情", "感人",
                "生活", "成长"
            ],
            VideoGenre.THRILLER: [
                "惊悚", "紧张", "刺激", "心跳", "悬疑",
                "高能", "紧凑"
            ],
        }

        self._ratio_recommendations = {
            VideoGenre.SUSPENSE: "9:16",
            VideoGenre.HORROR: "9:16",
            VideoGenre.ROMANCE: "9:16",
            VideoGenre.ACTION: "16:9",
            VideoGenre.COMEDY: "9:16",
            VideoGenre.DOCUMENTARY: "16:9",
            VideoGenre.DRAMA: "9:16",
            VideoGenre.THRILLER: "9:16",
            VideoGenre.UNKNOWN: "9:16",
        }

    def analyze_and_recommend(
        self,
        video_paths: List[str],
        video_info: Optional[List[Dict[str, Any]]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> ModeRecommendation:
        """
        分析视频并推荐最佳模式

        Args:
            video_paths: 视频路径列表
            video_info: 视频信息列表（可选）
            progress_callback: 进度回调

        Returns:
            ModeRecommendation: 推荐结果
        """
        if progress_callback:
            progress_callback(10, "分析视频数量...")

        analysis = self._analyze_videos(video_paths, video_info)

        if progress_callback:
            progress_callback(60, "分析内容特征...")

        recommendation = self._generate_recommendation(analysis)

        if progress_callback:
            progress_callback(100, "推荐完成")

        logger.info(
            f"[Recommender] 推荐模式: {recommendation.recommended_mode}, "
            f"置信度: {recommendation.confidence:.2f}"
        )

        return recommendation

    def _analyze_videos(
        self,
        video_paths: List[str],
        video_info: Optional[List[Dict[str, Any]]] = None,
    ) -> VideoAnalysis:
        """分析视频"""
        info_list = video_info or []

        total_duration = sum(
            (v.get("duration", 0) for v in info_list),
            sum(0 for _ in video_paths) if info_list else len(video_paths) * 300
        )

        subtitle_languages = []
        for v in info_list:
            if v.get("has_subtitle"):
                subtitle_languages.append(v.get("subtitle_lang", "zh"))

        dialogue_ratio = self._estimate_dialogue_ratio(info_list)
        genre = self._detect_genre(info_list)
        content_features = self._extract_content_features(info_list)
        audio_features = self._extract_audio_features(info_list)

        return VideoAnalysis(
            video_count=len(video_paths),
            total_duration=total_duration,
            has_subtitles=len(subtitle_languages) > 0,
            subtitle_languages=subtitle_languages,
            estimated_dialogue_ratio=dialogue_ratio,
            detected_genre=genre,
            content_features=content_features,
            audio_features=audio_features,
        )

    def _estimate_dialogue_ratio(self, video_info: List[Dict]) -> float:
        """估算对话占比"""
        if not video_info:
            return 0.5

        total_speech_time = sum(
            v.get("speech_duration", 0) for v in video_info
        )
        total_duration = sum(
            v.get("duration", 0) for v in video_info
        )

        if total_duration == 0:
            return 0.5

        return min(total_speech_time / total_duration, 1.0)

    def _detect_genre(self, video_info: List[Dict]) -> VideoGenre:
        """检测视频类型"""
        combined_text = ""

        for v in video_info:
            title = v.get("title", "")
            subtitle = v.get("subtitle_preview", "")
            description = v.get("description", "")
            combined_text += f" {title} {subtitle} {description}"

        combined_text = combined_text.lower()

        genre_scores = {}
        for genre, keywords in self._genre_keywords.items():
            score = sum(1 for kw in keywords if kw in combined_text)
            if score > 0:
                genre_scores[genre] = score

        if genre_scores:
            return max(genre_scores, key=genre_scores.get)
        return VideoGenre.UNKNOWN

    def _extract_content_features(self, video_info: List[Dict]) -> Dict[str, float]:
        """提取内容特征"""
        features = {
            "has_action": 0.0,
            "has_dialogue": 0.0,
            "has_emotion": 0.0,
            "is_fast_paced": 0.0,
        }

        for v in video_info:
            if v.get("has_action_sequence"):
                features["has_action"] = 1.0
            if v.get("dialogue_heavy"):
                features["has_dialogue"] = 1.0
            if v.get("emotional_content"):
                features["has_emotion"] = 1.0
            if v.get("fast_paced"):
                features["is_fast_paced"] = 1.0

        return features

    def _extract_audio_features(self, video_info: List[Dict]) -> Dict[str, float]:
        """提取音频特征"""
        features = {
            "avg_volume": 0.5,
            "music_present": 0.0,
            "sfx_present": 0.0,
        }

        if video_info:
            avg_volumes = [v.get("avg_volume", 0.5) for v in video_info]
            features["avg_volume"] = sum(avg_volumes) / len(avg_volumes)

        return features

    def _generate_recommendation(self, analysis: VideoAnalysis) -> ModeRecommendation:
        """生成推荐"""
        reasons = []
        alternatives = []
        confidence = 0.5

        video_count = analysis.video_count
        genre = analysis.detected_genre
        dialogue_ratio = analysis.estimated_dialogue_ratio

        if video_count >= 3:
            recommended_mode = ClipMode.ALL_THREE
            reasons.append(f"检测到{video_count}个剧集，适合一键生成三种版本")
            confidence = 0.9
            alternatives = [ClipMode.HYBRID, ClipMode.ORIGINAL]
        elif video_count == 1:
            if genre in [VideoGenre.ROMANCE, VideoGenre.DRAMA]:
                recommended_mode = ClipMode.HYBRID
                reasons.append("爱情/剧情类内容，混合解说能更好地传达情感")
                confidence = 0.8
            elif genre in [VideoGenre.SUSPENSE, VideoGenre.HORROR, VideoGenre.THRILLER]:
                recommended_mode = ClipMode.ORIGINAL
                reasons.append("悬疑/恐怖内容保持原汁原味更有冲击力")
                confidence = 0.85
            elif genre == VideoGenre.DOCUMENTARY:
                recommended_mode = ClipMode.FULL_NARRATION
                reasons.append("纪录片适合全解说模式提供更多信息")
                confidence = 0.75
            elif dialogue_ratio > 0.6:
                recommended_mode = ClipMode.HYBRID
                reasons.append("对话丰富的内容，混合解说可以突出重点")
                confidence = 0.7
            else:
                recommended_mode = ClipMode.ORIGINAL
                reasons.append("原片直剪保留原始观感")
                confidence = 0.6
            alternatives = [ClipMode.HYBRID, ClipMode.ORIGINAL]
        else:
            recommended_mode = ClipMode.HYBRID
            reasons.append("双集内容推荐混合解说")
            confidence = 0.65
            alternatives = [ClipMode.ORIGINAL, ClipMode.ALL_THREE]

        suggested_ratio = self._ratio_recommendations.get(genre, "9:16")
        reasons.append(f"检测类型: {genre.value}")

        target_duration = self._suggest_duration(genre, analysis.total_duration)
        auto_title_enabled = genre not in [VideoGenre.DOCUMENTARY]

        return ModeRecommendation(
            recommended_mode=recommended_mode,
            confidence=confidence,
            reasons=reasons,
            alternatives=alternatives,
            suggested_ratio=suggested_ratio,
            target_duration=target_duration,
            auto_title_enabled=auto_title_enabled,
        )

    def _suggest_duration(self, genre: VideoGenre, total_duration: float) -> Optional[int]:
        """建议目标时长"""
        duration_map = {
            VideoGenre.SUSPENSE: 90,
            VideoGenre.HORROR: 60,
            VideoGenre.ROMANCE: 120,
            VideoGenre.ACTION: 60,
            VideoGenre.COMEDY: 90,
            VideoGenre.DOCUMENTARY: 180,
            VideoGenre.DRAMA: 120,
            VideoGenre.THRILLER: 90,
            VideoGenre.UNKNOWN: 60,
        }

        base_duration = duration_map.get(genre, 90)

        if total_duration < base_duration:
            return int(total_duration * 0.8)

        return base_duration


_global_recommender: Optional[SmartModeRecommender] = None


def get_smart_recommender() -> SmartModeRecommender:
    """获取全局推荐器"""
    global _global_recommender
    if _global_recommender is None:
        _global_recommender = SmartModeRecommender()
    return _global_recommender
