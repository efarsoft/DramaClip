"""
高光选择器 - 根据打分结果筛选高光片段
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from loguru import logger


@dataclass
class HighlightSegment:
    """高光片段数据类"""

    video_path: str
    start_time: float  # 开始时间（秒）
    end_time: float  # 结束时间（秒）
    score: float = 0.0  # 总分
    audio_score: float = 0.0  # 音频分数
    emotion_score: float = 0.0  # 情绪分数
    visual_score: float = 0.0  # 画面分数
    rhythm_score: float = 0.0  # 节奏分数
    subtitle_text: Optional[str] = None  # 字幕文本
    reason: Optional[str] = None  # 入选理由
    segment_id: Optional[str] = None  # 前端传递的片段 ID（来自分析结果）
    dialogue_importance: float = 0.0  # 新增：原声保护重要性（0~1），用于 hybrid 模式优先保留有价值原声的片段
    speaker: Optional[str] = None           # P5: 来自 diarization 的 speaker_id (speaker_0 等)
    speaker_score: float = 0.0              # P5: 说话人重要性分数（主导角色加分、说话人切换节奏等）

    @property
    def duration(self) -> float:
        """片段时长（秒）"""
        return self.end_time - self.start_time

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "video_path": self.video_path,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "score": self.score,
            "audio_score": self.audio_score,
            "emotion_score": self.emotion_score,
            "visual_score": self.visual_score,
            "rhythm_score": self.rhythm_score,
            "subtitle_text": self.subtitle_text,
            "reason": self.reason,
            "segment_id": self.segment_id,
            "dialogue_importance": self.dialogue_importance,
            "speaker": self.speaker,                 # P5
            "speaker_score": self.speaker_score,     # P5
        }


class HighlightSelector:
    """高光片段选择器"""

    def __init__(
        self,
        top_ratio: float = 0.3,
        min_segment_duration: float = 2.0,
        max_segments_per_episode: int = 5,
        min_episodes_covered: int = 1,
    ):
        """
        初始化选择器

        Args:
            top_ratio: 选取Top N比例 (0.3 = Top 30%)
            min_segment_duration: 最小片段时长（秒）
            max_segments_per_episode: 每集最多保留片段数
            min_episodes_covered: 最少覆盖集数
        """
        self.top_ratio = top_ratio
        self.min_segment_duration = min_segment_duration
        self.max_segments_per_episode = max_segments_per_episode
        self.min_episodes_covered = min_episodes_covered

        logger.info(
            f"HighlightSelector initialized: "
            f"top_ratio={top_ratio}, min_duration={min_segment_duration}s, "
            f"max_per_ep={max_segments_per_episode}"
        )

    def select(
        self,
        segments: List[HighlightSegment],
        target_duration: Optional[int] = None,
    ) -> List[HighlightSegment]:
        """
        选择高光片段

        Args:
            segments: 候选片段列表
            target_duration: 目标总时长（秒，可选）。为 None 时不截断，返回所有入选片段

        Returns:
            选中的高光片段列表
        """
        if not segments:
            logger.warning("No segments to select from")
            return []

        logger.info(f"Selecting from {len(segments)} candidate segments")

        # 1. 过滤掉时长不足的片段
        filtered = [s for s in segments if s.duration >= self.min_segment_duration]
        logger.info(f"After duration filter (>= {self.min_segment_duration}s): {len(filtered)} segments")

        if not filtered:
            logger.warning("No segments left after duration filter")
            return []

        # 2. 按分数排序（降序）
        sorted_segments = sorted(filtered, key=lambda s: s.score, reverse=True)

        # 3. 选取Top N%
        top_n = max(1, int(len(sorted_segments) * self.top_ratio))
        top_segments = sorted_segments[:top_n]
        logger.info(f"Top {self.top_ratio*100}% segments: {len(top_segments)} segments")

        # 4. 按集数分组，限制每集最多片段数
        episode_groups = self._group_by_episode(top_segments)
        balanced_segments = self._balance_episodes(
            episode_groups, self.max_segments_per_episode
        )
        logger.info(f"After balancing (max {self.max_segments_per_episode}/ep): {len(balanced_segments)} segments")

        # 5. 确保最少覆盖集数
        if len(episode_groups) < self.min_episodes_covered:
            logger.warning(
                f"Only {len(episode_groups)} episodes covered, "
                f"minimum required: {self.min_episodes_covered}"
            )

        # 6. 按时间顺序重新排序
        balanced_segments.sort(key=lambda s: (s.video_path, s.start_time))

        # 7. 智能截断到目标时长
        final_segments = self._truncate_to_duration(
            balanced_segments, target_duration
        )

        # 8. 添加入选理由
        for seg in final_segments:
            seg.reason = self._generate_reason(seg)

        logger.info(
            f"Final selection: {len(final_segments)} segments, "
            f"total duration: {sum(s.duration for s in final_segments):.1f}s"
        )

        return final_segments

    def _group_by_episode(
        self, segments: List[HighlightSegment]
    ) -> Dict[str, List[HighlightSegment]]:
        """按集数分组"""
        groups = {}
        for seg in segments:
            # 从video_path提取集数信息（假设文件名包含集数）
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

    def _balance_episodes(
        self,
        episode_groups: Dict[str, List[HighlightSegment]],
        max_per_episode: int,
    ) -> List[HighlightSegment]:
        """平衡每集的片段数"""
        balanced = []
        for ep_key, segs in episode_groups.items():
            # 每集最多保留max_per_episode个片段
            balanced.extend(segs[:max_per_episode])
        return balanced

    def _truncate_to_duration(
        self,
        segments: List[HighlightSegment],
        target_duration: Optional[int] = None,
    ) -> List[HighlightSegment]:
        """
        智能截断到目标时长

        策略：
        1. 如果 target_duration 为 None，不截断，返回所有片段
        2. 优先保留高分片段
        3. 如果总时长超过目标，从最低分开始移除
        4. 尽量保留更多片段（短片段优先保留）
        """
        if not segments:
            return []

        # 不限制时长时，返回所有片段
        if target_duration is None:
            return segments

        # 计算当前总时长
        total_duration = sum(s.duration for s in segments)
        logger.info(f"Current total duration: {total_duration:.1f}s, target: {target_duration}s")

        if total_duration <= target_duration:
            #  already within target
            return segments

        # 按分数排序（升序），从最低分开始移除
        sorted_by_score = sorted(segments, key=lambda s: s.score)

        removed = []
        current_duration = total_duration

        for seg in sorted_by_score:
            if current_duration <= target_duration:
                break
            removed.append(seg)
            current_duration -= seg.duration

        # 返回未移除的片段
        final = [s for s in segments if s not in removed]
        logger.info(
            f"Truncated: removed {len(removed)} segments, "
            f"final duration: {sum(s.duration for s in final):.1f}s"
        )
        return final

    def _generate_reason(self, seg: HighlightSegment) -> str:
        """生成入选理由"""
        reasons = []

        if seg.audio_score >= 0.7:
            reasons.append("音频爆点强烈")
        if seg.emotion_score >= 0.7:
            reasons.append("情绪高涨")
        if seg.visual_score >= 0.7:
            reasons.append("画面动感强")
        if seg.rhythm_score >= 0.7:
            reasons.append("节奏紧凑")

        if not reasons:
            if seg.score >= 0.7:
                reasons.append("综合高分")
            else:
                reasons.append("候选高光")

        return "、".join(reasons)

    def select_from_scores(
        self,
        scored_segments: List[Dict],
        video_paths: List[str],
        start_times: List[float],
        end_times: List[float],
        subtitle_texts: Optional[List[Optional[str]]] = None,
        target_duration: Optional[int] = None,
    ) -> List[HighlightSegment]:
        """
        从打分结果直接选择高光片段

        Args:
            scored_segments: 打分结果列表（每个元素包含各维度分数）
            video_paths: 对应视频路径列表
            start_times: 开始时间列表
            end_times: 结束时间列表
            subtitle_texts: 字幕文本列表（可选）
            target_duration: 目标总时长（秒）

        Returns:
            选中的高光片段列表
        """
        if subtitle_texts is None:
            subtitle_texts = [None] * len(scored_segments)

        # 转换为HighlightSegment对象
        # 当video_paths长度小于segment数量时，循环使用（单视频多片段场景）
        segments = []
        for i, score_dict in enumerate(scored_segments):
            vp = video_paths[i % len(video_paths)] if video_paths else ""
            
            def get_float_score(key: str) -> float:
                val = score_dict.get(key, 0.0)
                if val is None:
                    return 0.0
                if isinstance(val, dict):
                    # 如果不小心传入了字典，尝试取其中的 score/intensity 字段或默认值
                    return float(val.get("score") or val.get("motion_score") or val.get("energy") or 0.5)
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return 0.0

            # 如果没有total_score，从各维度加权计算
            # P5: 加入 speaker_score 小权重（pyannote 精准模式下会产生更有意义的 speaker-aware 高光）
            total = score_dict.get("total_score", None)
            if total is None:
                total = (
                    get_float_score("audio_score") * 0.38
                    + get_float_score("emotion_score") * 0.28
                    + get_float_score("visual_score") * 0.18
                    + get_float_score("rhythm_score") * 0.08
                    + get_float_score("speaker_score") * 0.08   # P5
                )
            else:
                try:
                    total = float(total)
                except (ValueError, TypeError):
                    total = 0.0

            seg = HighlightSegment(
                video_path=vp,
                start_time=start_times[i],
                end_time=end_times[i],
                score=total,
                audio_score=get_float_score("audio_score"),
                emotion_score=get_float_score("emotion_score"),
                visual_score=get_float_score("visual_score"),
                rhythm_score=get_float_score("rhythm_score"),
                dialogue_importance=get_float_score("dialogue_importance"),
                speaker_score=get_float_score("speaker_score"),   # P5
                speaker=score_dict.get("speaker"),                # P5
                subtitle_text=subtitle_texts[i],
            )
            segments.append(seg)

        # 调用select方法
        return self.select(segments, target_duration)
