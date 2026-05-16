"""
HighlightSelector 单元测试
"""

import pytest
import sys
from pathlib import Path

# 确保 app 在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.highlight.selector import HighlightSelector, HighlightSegment


@pytest.fixture
def selector():
    """创建选择器实例"""
    return HighlightSelector(
        top_ratio=0.3,
        min_segment_duration=2.0,
        max_segments_per_episode=5,
        min_episodes_covered=1,
    )


@pytest.fixture
def sample_segments():
    """创建示例片段列表"""
    return [
        HighlightSegment(
            video_path="episode1.mp4",
            start_time=10.0,
            end_time=15.0,
            score=0.9,
            audio_score=0.8,
            emotion_score=0.9,
            visual_score=0.7,
            rhythm_score=0.6,
        ),
        HighlightSegment(
            video_path="episode1.mp4",
            start_time=30.0,
            end_time=35.0,
            score=0.7,
            audio_score=0.6,
            emotion_score=0.7,
            visual_score=0.5,
            rhythm_score=0.4,
        ),
        HighlightSegment(
            video_path="episode1.mp4",
            start_time=50.0,
            end_time=53.0,
            score=0.5,
            audio_score=0.4,
            emotion_score=0.5,
            visual_score=0.3,
            rhythm_score=0.2,
        ),
        HighlightSegment(
            video_path="episode2.mp4",
            start_time=5.0,
            end_time=10.0,
            score=0.85,
            audio_score=0.7,
            emotion_score=0.8,
            visual_score=0.6,
            rhythm_score=0.5,
        ),
        HighlightSegment(
            video_path="episode2.mp4",
            start_time=20.0,
            end_time=22.0,  # 时长 2 秒，刚好达到最小值
            score=0.6,
            audio_score=0.5,
            emotion_score=0.6,
            visual_score=0.4,
            rhythm_score=0.3,
        ),
    ]


class TestHighlightSegment:
    """HighlightSegment 测试"""

    def test_duration(self):
        """应正确计算时长"""
        seg = HighlightSegment(
            video_path="test.mp4",
            start_time=10.0,
            end_time=15.0,
            score=0.8,
            audio_score=0.7,
            emotion_score=0.6,
            visual_score=0.5,
            rhythm_score=0.4,
        )
        assert seg.duration == 5.0

    def test_to_dict(self):
        """应正确转换为字典"""
        seg = HighlightSegment(
            video_path="test.mp4",
            start_time=10.0,
            end_time=15.0,
            score=0.8,
            audio_score=0.7,
            emotion_score=0.6,
            visual_score=0.5,
            rhythm_score=0.4,
            subtitle_text="测试字幕",
            reason="音频爆点强烈",
        )

        d = seg.to_dict()

        assert d["video_path"] == "test.mp4"
        assert d["start_time"] == 10.0
        assert d["end_time"] == 15.0
        assert d["duration"] == 5.0
        assert d["score"] == 0.8
        assert d["subtitle_text"] == "测试字幕"
        assert d["reason"] == "音频爆点强烈"


class TestHighlightSelector:
    """HighlightSelector 测试"""

    def test_select_empty_segments(self, selector):
        """空片段列表应返回空列表"""
        result = selector.select([])
        assert result == []

    def test_select_filters_short_segments(self, selector):
        """应过滤掉时长不足的片段"""
        segments = [
            HighlightSegment(
                video_path="test.mp4",
                start_time=0.0,
                end_time=1.0,  # 1 秒，低于最小值 2 秒
                score=0.9,
                audio_score=0.8,
                emotion_score=0.7,
                visual_score=0.6,
                rhythm_score=0.5,
            ),
            HighlightSegment(
                video_path="test.mp4",
                start_time=10.0,
                end_time=15.0,  # 5 秒，符合要求
                score=0.7,
                audio_score=0.6,
                emotion_score=0.5,
                visual_score=0.4,
                rhythm_score=0.3,
            ),
        ]

        result = selector.select(segments)
        assert len(result) == 1
        assert result[0].start_time == 10.0

    def test_select_top_ratio(self, selector, sample_segments):
        """应按比例选取高分片段"""
        result = selector.select(sample_segments)

        # top_ratio=0.3, 5 个片段 * 0.3 = 1.5 -> 取 1 个
        # 但会经过多轮过滤，最终数量可能不同
        assert len(result) > 0

        # 验证结果按时间顺序排序
        for i in range(len(result) - 1):
            if result[i].video_path == result[i + 1].video_path:
                assert result[i].start_time <= result[i + 1].start_time

    def test_select_with_target_duration(self, selector, sample_segments):
        """应按目标时长截断"""
        result = selector.select(sample_segments, target_duration=10)

        total_duration = sum(s.duration for s in result)
        assert total_duration <= 10

    def test_select_adds_reason(self, selector, sample_segments):
        """应为选中片段添加入选理由"""
        result = selector.select(sample_segments)

        for seg in result:
            assert seg.reason is not None
            assert len(seg.reason) > 0

    def test_select_from_scores(self, selector):
        """应能从打分结果直接选择"""
        scored_segments = [
            {
                "audio_score": 0.8,
                "emotion_score": 0.7,
                "visual_score": 0.6,
                "rhythm_score": 0.5,
                "total_score": 0.7,
            },
            {
                "audio_score": 0.4,
                "emotion_score": 0.3,
                "visual_score": 0.2,
                "rhythm_score": 0.1,
                "total_score": 0.3,
            },
        ]

        result = selector.select_from_scores(
            scored_segments=scored_segments,
            video_paths=["test.mp4"],
            start_times=[10.0, 30.0],
            end_times=[15.0, 35.0],
        )

        assert len(result) > 0
        assert all(isinstance(s, HighlightSegment) for s in result)

    def test_group_by_episode(self, selector, sample_segments):
        """应按集数分组"""
        groups = selector._group_by_episode(sample_segments)

        assert "episode1.mp4" in groups
        assert "episode2.mp4" in groups
        assert len(groups["episode1.mp4"]) == 3
        assert len(groups["episode2.mp4"]) == 2

    def test_balance_episodes(self, selector):
        """应限制每集最多片段数"""
        episode_groups = {
            "ep1.mp4": [
                HighlightSegment("ep1.mp4", 0, 5, 0.9, 0.8, 0.7, 0.6, 0.5),
                HighlightSegment("ep1.mp4", 10, 15, 0.8, 0.7, 0.6, 0.5, 0.4),
                HighlightSegment("ep1.mp4", 20, 25, 0.7, 0.6, 0.5, 0.4, 0.3),
            ],
        }

        balanced = selector._balance_episodes(episode_groups, max_per_episode=2)
        assert len(balanced) == 2

    def test_truncate_to_duration_no_limit(self, selector):
        """无目标时长限制时应返回所有片段"""
        segments = [
            HighlightSegment("test.mp4", 0, 10, 0.9, 0.8, 0.7, 0.6, 0.5),
            HighlightSegment("test.mp4", 20, 30, 0.7, 0.6, 0.5, 0.4, 0.3),
        ]

        result = selector._truncate_to_duration(segments, target_duration=None)
        assert len(result) == 2

    def test_truncate_to_duration_within_limit(self, selector):
        """总时长在限制内时应返回所有片段"""
        segments = [
            HighlightSegment("test.mp4", 0, 5, 0.9, 0.8, 0.7, 0.6, 0.5),
            HighlightSegment("test.mp4", 10, 15, 0.7, 0.6, 0.5, 0.4, 0.3),
        ]

        result = selector._truncate_to_duration(segments, target_duration=20)
        assert len(result) == 2

    def test_truncate_to_duration_exceeds_limit(self, selector):
        """总时长超过限制时应移除低分片段"""
        segments = [
            HighlightSegment("test.mp4", 0, 10, 0.9, 0.8, 0.7, 0.6, 0.5),  # 10秒
            HighlightSegment("test.mp4", 20, 30, 0.5, 0.4, 0.3, 0.2, 0.1),  # 10秒
        ]

        result = selector._truncate_to_duration(segments, target_duration=10)
        assert len(result) == 1
        assert result[0].score == 0.9  # 保留高分片段

    def test_generate_reason_high_audio(self, selector):
        """高音频分数应生成对应理由"""
        seg = HighlightSegment("test.mp4", 0, 5, 0.8, 0.8, 0.3, 0.3, 0.3)
        reason = selector._generate_reason(seg)
        assert "音频爆点" in reason

    def test_generate_reason_high_emotion(self, selector):
        """高情绪分数应生成对应理由"""
        seg = HighlightSegment("test.mp4", 0, 5, 0.8, 0.3, 0.8, 0.3, 0.3)
        reason = selector._generate_reason(seg)
        assert "情绪" in reason

    def test_generate_reason_general_high_score(self, selector):
        """综合高分应生成对应理由"""
        seg = HighlightSegment("test.mp4", 0, 5, 0.8, 0.5, 0.5, 0.5, 0.5)
        reason = selector._generate_reason(seg)
        assert "综合高分" in reason or "候选高光" in reason
