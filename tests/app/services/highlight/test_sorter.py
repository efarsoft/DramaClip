"""
HighlightSorter 单元测试
"""

import pytest
import sys
from pathlib import Path

# 确保 app 在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.highlight.sorter import HighlightSorter, SortStrategy
from app.services.highlight.selector import HighlightSegment


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
            video_path="episode2.mp4",
            start_time=5.0,
            end_time=10.0,
            score=0.85,
            audio_score=0.7,
            emotion_score=0.8,
            visual_score=0.6,
            rhythm_score=0.5,
        ),
    ]


class TestSortStrategy:
    """SortStrategy 枚举测试"""

    def test_strategies_exist(self):
        """所有排序策略应存在"""
        assert SortStrategy.CHRONOLOGICAL == "chronological"
        assert SortStrategy.BY_SCORE == "by_score"
        assert SortStrategy.EMOTION_PROGRESSION == "emotion_progression"
        assert SortStrategy.SMART_SHUFFLE == "smart_shuffle"

    def test_strategy_value(self):
        """策略值应为字符串"""
        for strategy in SortStrategy:
            assert isinstance(strategy.value, str)


class TestHighlightSorter:
    """HighlightSorter 测试"""

    def test_init_default_strategy(self):
        """默认策略应为 CHRONOLOGICAL"""
        sorter = HighlightSorter()
        assert sorter.strategy == SortStrategy.CHRONOLOGICAL

    def test_init_custom_strategy(self):
        """应能设置自定义策略"""
        sorter = HighlightSorter(strategy=SortStrategy.BY_SCORE)
        assert sorter.strategy == SortStrategy.BY_SCORE

    def test_sort_empty_segments(self):
        """空片段列表应返回空列表"""
        sorter = HighlightSorter()
        result = sorter.sort([])
        assert result == []

    def test_sort_chronological(self, sample_segments):
        """按时间排序应正确"""
        sorter = HighlightSorter(strategy=SortStrategy.CHRONOLOGICAL)
        result = sorter.sort(sample_segments)

        # 验证按视频路径和开始时间排序
        for i in range(len(result) - 1):
            if result[i].video_path == result[i + 1].video_path:
                assert result[i].start_time <= result[i + 1].start_time

    def test_sort_by_score(self, sample_segments):
        """按分数排序应正确"""
        sorter = HighlightSorter(strategy=SortStrategy.BY_SCORE)
        result = sorter.sort(sample_segments, target_duration=0)  # 不截断

        # 验证按分数降序排序
        for i in range(len(result) - 1):
            assert result[i].score >= result[i + 1].score

    def test_sort_with_target_duration(self, sample_segments):
        """应按目标时长截断"""
        sorter = HighlightSorter(strategy=SortStrategy.BY_SCORE)
        result = sorter.sort(sample_segments, target_duration=10)

        total_duration = sum(s.duration for s in result)
        assert total_duration <= 10

    def test_sort_no_truncation_when_zero(self, sample_segments):
        """target_duration=0 时不应截断"""
        sorter = HighlightSorter(strategy=SortStrategy.BY_SCORE)
        result = sorter.sort(sample_segments, target_duration=0)

        # 应返回所有片段
        assert len(result) == len(sample_segments)

    def test_sort_preserves_segments(self, sample_segments):
        """排序不应修改原始片段"""
        sorter = HighlightSorter(strategy=SortStrategy.BY_SCORE)
        original_scores = [s.score for s in sample_segments]

        sorter.sort(sample_segments)

        # 验证原始片段未被修改
        for i, seg in enumerate(sample_segments):
            assert seg.score == original_scores[i]

    def test_truncate_to_duration_no_limit(self):
        """无目标时长限制时应返回所有片段"""
        sorter = HighlightSorter()
        segments = [
            HighlightSegment("test.mp4", 0, 10, 0.9, 0.8, 0.7, 0.6, 0.5),
            HighlightSegment("test.mp4", 20, 30, 0.7, 0.6, 0.5, 0.4, 0.3),
        ]

        result = sorter._truncate_to_duration(segments, target_duration=0)
        assert len(result) == 2

    def test_truncate_to_duration_within_limit(self):
        """总时长在限制内时应返回所有片段"""
        sorter = HighlightSorter()
        segments = [
            HighlightSegment("test.mp4", 0, 5, 0.9, 0.8, 0.7, 0.6, 0.5),
            HighlightSegment("test.mp4", 10, 15, 0.7, 0.6, 0.5, 0.4, 0.3),
        ]

        result = sorter._truncate_to_duration(segments, target_duration=20)
        assert len(result) == 2

    def test_truncate_to_duration_exceeds_limit(self):
        """总时长超过限制时应移除低分片段"""
        sorter = HighlightSorter()
        segments = [
            HighlightSegment("test.mp4", 0, 10, 0.9, 0.8, 0.7, 0.6, 0.5),  # 10秒
            HighlightSegment("test.mp4", 20, 30, 0.5, 0.4, 0.3, 0.2, 0.1),  # 10秒
        ]

        result = sorter._truncate_to_duration(segments, target_duration=10)
        assert len(result) == 1
        assert result[0].score == 0.9  # 保留高分片段

    def test_sort_emotion_progression(self, sample_segments):
        """情绪递进排序应正确"""
        sorter = HighlightSorter(strategy=SortStrategy.EMOTION_PROGRESSION)
        result = sorter.sort(sample_segments, target_duration=0)

        # 应返回排序后的片段
        assert len(result) == len(sample_segments)

    def test_sort_smart_shuffle(self, sample_segments):
        """智能混排应正确"""
        sorter = HighlightSorter(strategy=SortStrategy.SMART_SHUFFLE)
        result = sorter.sort(sample_segments, target_duration=0)

        # 应返回排序后的片段
        assert len(result) == len(sample_segments)
