"""
场景排序器 - 对高光片段进行智能排序，确保剧情流畅、情绪递进
"""

import logging
from typing import Dict, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class SortStrategy(str, Enum):
    """排序策略枚举"""

    CHRONOLOGICAL = "chronological"  # 按时间顺序（默认）
    EMOTION_CURVE = "emotion_curve"  # 情绪曲线（起承转合）
    DIVERSITY_FIRST = "diversity_first"  # 多样性优先（避免连续同一场景）


class SceneSorter:
    """场景排序器 - 确保剧情流畅、情绪递进"""

    def __init__(
        self,
        strategy: SortStrategy = SortStrategy.CHRONOLOGICAL,
        max_same_episode_consecutive: int = 2,  # 同一集最多连续出现次数
    ):
        """
        初始化排序器

        Args:
            strategy: 排序策略
            max_same_episode_consecutive: 同一集最多连续出现次数（避免审美疲劳）
        """
        self.strategy = strategy
        self.max_same_episode_consecutive = max_same_episode_consecutive

        logger.info(
            f"SceneSorter initialized: strategy={strategy.value}, "
            f"max_same_ep_consecutive={max_same_episode_consecutive}"
        )

    def sort(
        self,
        segments: List["HighlightSegment"],
    ) -> List["HighlightSegment"]:
        """
        对高光片段进行排序

        Args:
            segments: 高光片段列表

        Returns:
            排序后的高光片段列表
        """
        if not segments:
            logger.warning("No segments to sort")
            return []

        logger.info(
            f"Sorting {len(segments)} segments using strategy: {self.strategy.value}"
        )

        # 根据策略排序
        if self.strategy == SortStrategy.CHRONOLOGICAL:
            sorted_segments = self._sort_chronological(segments)
        elif self.strategy == SortStrategy.EMOTION_CURVE:
            sorted_segments = self._sort_emotion_curve(segments)
        elif self.strategy == SortStrategy.DIVERSITY_FIRST:
            sorted_segments = self._sort_diversity_first(segments)
        else:
            logger.warning(f"Unknown strategy: {self.strategy}, using chronological")
            sorted_segments = self._sort_chronological(segments)

        logger.info(f"Sorted {len(sorted_segments)} segments")
        return sorted_segments

    def _sort_chronological(
        self, segments: List["HighlightSegment"]
    ) -> List["HighlightSegment"]:
        """
        按时间顺序排序（默认策略）

        保证剧情连贯性，按照：
        1. 集数顺序
        2. 片段在集中的时间顺序
        """
        return sorted(segments, key=lambda s: (self._extract_episode(s.video_path), s.start_time))

    def _sort_emotion_curve(
        self, segments: List["HighlightSegment"]
    ) -> List["HighlightSegment"]:
        """
        情绪曲线排序（起承转合）

        目标：创建一个完整的情绪弧线
        1. 起（铺垫）：低情绪、正情绪 → 温和开场
        2. 承（发展）：情绪逐渐升温
        3. 转（冲突）：高情绪、负情绪 → 冲突爆发
        4. 合（高潮/结尾）：最高情绪爆点

        适用于：希望在短时间内讲述完整故事的情况
        """
        if not segments:
            return []

        # 1. 分类情绪类型
        categorized = self._categorize_emotions(segments)

        # 2. 构建情绪曲线
        ordered = []

        # 起：低唤醒正情绪（温暖、感动、希望）
        opening = sorted(
            categorized.get("low_arousal_positive", []),
            key=lambda s: s.start_time,
        )
        ordered.extend(opening[:1])  # 只取1个作为开头

        # 承：中低情绪（任何类型，按时间顺序）
        developing = (
            categorized.get("low_arousal_negative", [])
            + categorized.get("high_arousal_positive", [])[:1]
        )
        developing.sort(key=lambda s: s.start_time)
        ordered.extend(developing[:2])

        # 转：高唤醒负情绪（愤怒、恐惧、冲突）
        conflict = sorted(
            categorized.get("high_arousal_negative", []),
            key=lambda s: s.score,
            reverse=True,
        )
        ordered.extend(conflict[:1])  # 取分数最高的冲突片段

        # 合：高唤醒正情绪（喜悦、胜利、团圆）
        climax = sorted(
            categorized.get("high_arousal_positive", []),
            key=lambda s: s.score,
            reverse=True,
        )
        ordered.extend(climax[:1])  # 取分数最高的高潮片段

        # 3. 添加剩余片段（按时间顺序）
        used = set(id(s) for s in ordered)
        remaining = [s for s in segments if id(s) not in used]
        remaining.sort(key=lambda s: s.start_time)
        ordered.extend(remaining)

        logger.info(
            f"Emotion curve: 起({len(opening[:1])}) → "
            f"承({len(developing[:2])}) → "
            f"转({len(conflict[:1])}) → "
            f"合({len(climax[:1])})"
        )

        return ordered

    def _sort_diversity_first(
        self, segments: List["HighlightSegment"]
    ) -> List["HighlightSegment"]:
        """
        多样性优先排序

        目标：避免审美疲劳，保证观感多样性
        策略：
        1. 按集数分组
        2. 轮询从各集选取片段
        3. 保证相邻片段来自不同集数
        4. 限制同一集连续出现次数

        适用于：希望展示多个精彩瞬间，而非单一剧情线的情况
        """
        if not segments:
            return []

        # 1. 按集数分组
        episode_groups = self._group_by_episode(segments)

        # 2. 对每组按分数排序（降序）
        for ep_key in episode_groups:
            episode_groups[ep_key].sort(key=lambda s: s.score, reverse=True)

        # 3. 轮询从各集选取片段
        shuffled = []
        episode_keys = list(episode_groups.keys())
        indices = {k: 0 for k in episode_keys}

        # 记录连续同一集的次数
        consecutive_count = 0
        last_ep_key = None

        while True:
            added = False
            for ep_key in episode_keys:
                # 检查是否应该跳过此集（避免连续出现太多次）
                if (
                    ep_key == last_ep_key
                    and consecutive_count >= self.max_same_episode_consecutive
                ):
                    continue

                seg_list = episode_groups[ep_key]
                idx = indices[ep_key]
                if idx < len(seg_list):
                    shuffled.append(seg_list[idx])
                    indices[ep_key] += 1
                    added = True

                    # 更新连续计数
                    if ep_key == last_ep_key:
                        consecutive_count += 1
                    else:
                        consecutive_count = 1
                    last_ep_key = ep_key

            if not added:
                break

        logger.info(f"Diversity-first sorting: {len(shuffled)} segments")
        return shuffled

    def _categorize_emotions(
        self, segments: List["HighlightSegment"]
    ) -> Dict[str, List["HighlightSegment"]]:
        """
        将片段按情绪类型分类

        分类依据：
        - emotion_score: 情绪强度（0~1）
        - audio_score: 音频能量（间接反映唤醒度）

        分类结果：
        1. high_arousal_positive: 高唤醒正情绪（兴奋、喜悦、胜利）
        2. high_arousal_negative: 高唤醒负情绪（愤怒、恐惧、冲突）
        3. low_arousal_positive: 低唤醒正情绪（温暖、感动、平静）
        4. low_arousal_negative: 低唤醒负情绪（悲伤、失望、犹豫）
        """
        categorized = {
            "high_arousal_positive": [],
            "high_arousal_negative": [],
            "low_arousal_positive": [],
            "low_arousal_negative": [],
        }

        for seg in segments:
            # 简化判断：基于emotion_score和audio_score
            is_high_arousal = seg.audio_score >= 0.5  # 音频能量高 → 高唤醒
            is_positive = seg.emotion_score >= 0.5  # 情绪分数高 → 正情绪

            if is_high_arousal and is_positive:
                categorized["high_arousal_positive"].append(seg)
            elif is_high_arousal and not is_positive:
                categorized["high_arousal_negative"].append(seg)
            elif not is_high_arousal and is_positive:
                categorized["low_arousal_positive"].append(seg)
            else:
                categorized["low_arousal_negative"].append(seg)

        return categorized

    def _group_by_episode(
        self, segments: List["HighlightSegment"]
    ) -> Dict[str, List["HighlightSegment"]]:
        """按集数分组"""
        groups = {}
        for seg in segments:
            ep_key = self._extract_episode_key(seg.video_path)
            if ep_key not in groups:
                groups[ep_key] = []
            groups[ep_key].append(seg)
        return groups

    def _extract_episode_key(self, video_path: str) -> str:
        """从视频路径提取集数标识"""
        import os
        filename = os.path.basename(video_path)
        # 简单处理：使用文件名作为key（实际应该提取集数）
        return filename

    def _extract_episode(self, video_path: str) -> int:
        """从视频路径提取集数（用于排序）"""
        # 简化实现：返回0（实际应该从文件名提取集数）
        # 例如："第01集.mp4" → 1
        return 0

    def set_strategy(self, strategy: SortStrategy):
        """动态修改排序策略"""
        self.strategy = strategy
        logger.info(f"Strategy changed to: {strategy.value}")

    def get_strategy(self) -> SortStrategy:
        """获取当前排序策略"""
        return self.strategy
