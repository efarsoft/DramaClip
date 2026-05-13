"""
高光排序器 - 对高光片段进行智能排序
"""

import logging
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class SortStrategy(str, Enum):
    """排序策略枚举"""

    CHRONOLOGICAL = "chronological"  # 按时间顺序
    BY_SCORE = "by_score"  # 按分数高低
    EMOTION_PROGRESSION = "emotion_progression"  # 情绪递进
    SMART_SHUFFLE = "smart_shuffle"  # 智能混排


class HighlightSorter:
    """高光片段排序器"""

    def __init__(
        self,
        strategy: SortStrategy = SortStrategy.CHRONOLOGICAL,
        emotion_weights: Optional[Dict[str, float]] = None,
    ):
        """
        初始化排序器

        Args:
            strategy: 排序策略
            emotion_weights: 情绪权重（用于情绪递进策略）
        """
        self.strategy = strategy
        self.emotion_weights = emotion_weights or {
            "high_arousal_negative": 1.0,  # 高唤醒负情绪（愤怒、恐惧）→ 优先
            "high_arousal_positive": 0.8,  # 高唤醒正情绪（兴奋、喜悦）
            "low_arousal_negative": 0.6,  # 低唤醒负情绪（悲伤、失望）
            "low_arousal_positive": 0.7,  # 低唤醒正情绪（温暖、感动）
        }

        logger.info(f"HighlightSorter initialized with strategy: {strategy.value}")

    def sort(
        self,
        segments: List["HighlightSegment"],
        target_duration: int = 30,
    ) -> List["HighlightSegment"]:
        """
        对高光片段进行排序

        Args:
            segments: 高光片段列表
            target_duration: 目标总时长（秒），用于智能截断

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
        elif self.strategy == SortStrategy.BY_SCORE:
            sorted_segments = self._sort_by_score(segments)
        elif self.strategy == SortStrategy.EMOTION_PROGRESSION:
            sorted_segments = self._sort_emotion_progression(segments)
        elif self.strategy == SortStrategy.SMART_SHUFFLE:
            sorted_segments = self._sort_smart_shuffle(segments)
        else:
            logger.warning(f"Unknown strategy: {self.strategy}, using chronological")
            sorted_segments = self._sort_chronological(segments)

        # 智能截断到目标时长
        if target_duration > 0:
            sorted_segments = self._truncate_to_duration(
                sorted_segments, target_duration
            )

        logger.info(
            f"Final sorted segments: {len(sorted_segments)}, "
            f"total duration: {sum(s.duration for s in sorted_segments):.1f}s"
        )

        return sorted_segments

    def _sort_chronological(
        self, segments: List["HighlightSegment"]
    ) -> List["HighlightSegment"]:
        """按时间顺序排序"""
        return sorted(segments, key=lambda s: (s.video_path, s.start_time))

    def _sort_by_score(
        self, segments: List["HighlightSegment"]
    ) -> List["HighlightSegment"]:
        """按分数降序排序（高分在前）"""
        return sorted(segments, key=lambda s: s.score, reverse=True)

    def _sort_emotion_progression(
        self, segments: List["HighlightSegment"]
    ) -> List["HighlightSegment"]:
        """
        情绪递进排序

        目标：创建一个情绪曲线，让观众情绪逐步升温
        策略：
        1. 开头：低唤醒情绪（铺垫）
        2. 中间：高唤醒情绪（冲突升级）
        3. 结尾：最高情绪爆点（高潮）
        """
        if not segments:
            return []

        # 1. 分类情绪类型
        categorized = self._categorize_emotions(segments)

        # 2. 构建情绪曲线
        # 开头：低唤醒正情绪（温暖、感动）
        opening = categorized.get("low_arousal_positive", [])

        # 早期冲突：低唤醒负情绪（悲伤、失望）
        early_conflict = categorized.get("low_arousal_negative", [])

        # 中期升级：高唤醒正情绪（兴奋、喜悦）
        mid_upgrade = categorized.get("high_arousal_positive", [])

        # 高潮：高唤醒负情绪（愤怒、恐惧）→ 反转 → 高唤醒正情绪
        climax_negative = categorized.get("high_arousal_negative", [])
        climax_positive = categorized.get("high_arousal_positive", [])

        # 3. 按情绪曲线重新排列
        ordered = []
        ordered.extend(opening[:1])  # 开头铺垫
        ordered.extend(early_conflict[:1])  # 早期冲突
        ordered.extend(mid_upgrade[:2])  # 中期升级
        ordered.extend(climax_negative[:1])  # 高潮前的压抑
        ordered.extend(climax_positive[:1])  # 高潮爆发

        # 4. 添加剩余片段（按分数排序）
        used = set(id(s) for s in ordered)
        remaining = [s for s in segments if id(s) not in used]
        remaining.sort(key=lambda s: s.score, reverse=True)
        ordered.extend(remaining)

        return ordered

    def _categorize_emotions(
        self, segments: List["HighlightSegment"]
    ) -> Dict[str, List["HighlightSegment"]]:
        """将片段按情绪类型分类"""
        categorized = {
            "high_arousal_negative": [],  # 高唤醒负情绪
            "high_arousal_positive": [],  # 高唤醒正情绪
            "low_arousal_negative": [],  # 低唤醒负情绪
            "low_arousal_positive": [],  # 低唤醒正情绪
        }

        for seg in segments:
            # 简化的情绪分类（基于emotion_score和audio_score）
            if seg.emotion_score >= 0.6:
                if seg.audio_score >= 0.6:
                    categorized["high_arousal_positive"].append(seg)
                else:
                    categorized["low_arousal_positive"].append(seg)
            else:
                if seg.audio_score >= 0.6:
                    categorized["high_arousal_negative"].append(seg)
                else:
                    categorized["low_arousal_negative"].append(seg)

        return categorized

    def _sort_smart_shuffle(
        self, segments: List["HighlightSegment"]
    ) -> List["HighlightSegment"]:
        """
        智能混排

        策略：
        1. 保证相邻片段来自不同集数（避免审美疲劳）
        2. 情绪有起伏（高-低-高）
        3. 分数分布均匀（避免高分集中）
        """
        if not segments:
            return []

        # 1. 按集数分组
        episode_groups = self._group_by_episode(segments)

        # 2. 轮询从各集选取片段
        shuffled = []
        episode_keys = list(episode_groups.keys())
        indices = {k: 0 for k in episode_keys}

        while True:
            added = False
            for ep_key in episode_keys:
                seg_list = episode_groups[ep_key]
                idx = indices[ep_key]
                if idx < len(seg_list):
                    shuffled.append(seg_list[idx])
                    indices[ep_key] += 1
                    added = True

            if not added:
                break

        # 3. 微调顺序，确保情绪有起伏
        shuffled = self._adjust_emotion_flow(shuffled)

        return shuffled

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
        return filename

    def _adjust_emotion_flow(
        self, segments: List["HighlightSegment"]
    ) -> List["HighlightSegment"]:
        """
        调整情绪流，避免连续高情绪导致审美疲劳

        策略：高情绪片段后插入中等或低情绪片段
        """
        if len(segments) <= 2:
            return segments

        adjusted = [segments[0]]

        for i in range(1, len(segments)):
            current = segments[i]
            prev = adjusted[-1]

            # 如果前一个是高情绪，当前也是高情绪，尝试插入一个中等情绪的
            if prev.emotion_score >= 0.6 and current.emotion_score >= 0.6:
                # 查找一个中等情绪的片段
                mid_emotion = next(
                    (
                        s
                        for s in segments
                        if s not in adjusted
                        and 0.3 <= s.emotion_score < 0.6
                    ),
                    None,
                )
                if mid_emotion:
                    adjusted.append(mid_emotion)

            adjusted.append(current)

        return adjusted

    def _truncate_to_duration(
        self,
        segments: List["HighlightSegment"],
        target_duration: int,
    ) -> List["HighlightSegment"]:
        """
        智能截断到目标时长

        策略：
        1. 优先保留高分片段
        2. 保证情绪曲线完整（不能去掉高潮部分）
        3. 尽量保留更多片段（短片段优先）
        """
        if not segments:
            return []

        # 计算当前总时长
        total_duration = sum(s.duration for s in segments)

        if total_duration <= target_duration:
            return segments

        # 按策略不同，截断逻辑不同
        if self.strategy == SortStrategy.EMOTION_PROGRESSION:
            # 情绪递进策略：保证开头-发展-高潮的完整性
            return self._truncate_preserve_curve(segments, target_duration)
        else:
            # 其他策略：从最低分开始移除
            return self._truncate_by_score(segments, target_duration)

    def _truncate_preserve_curve(
        self,
        segments: List["HighlightSegment"],
        target_duration: int,
    ) -> List["HighlightSegment"]:
        """截断时保留情绪曲线完整性"""
        # 简化实现：保留前80%（保证情绪递进）
        keep_count = max(1, int(len(segments) * 0.8))
        truncated = segments[:keep_count]

        # 如果还是超时长，从末尾开始移除
        while (
            truncated
            and sum(s.duration for s in truncated) > target_duration
        ):
            truncated.pop()

        return truncated

    def _truncate_by_score(
        self,
        segments: List["HighlightSegment"],
        target_duration: int,
    ) -> List["HighlightSegment"]:
        """按分数截断（低分先移除）"""
        # 按分数排序（升序）
        sorted_by_score = sorted(segments, key=lambda s: s.score)

        removed = []
        current_duration = sum(s.duration for s in segments)

        for seg in sorted_by_score:
            if current_duration <= target_duration:
                break
            removed.append(seg)
            current_duration -= seg.duration

        # 返回未移除的片段（保持原顺序）
        final = [s for s in segments if s not in removed]
        return final

    def set_strategy(self, strategy: SortStrategy):
        """动态修改排序策略"""
        self.strategy = strategy
        logger.info(f"Strategy changed to: {strategy.value}")
