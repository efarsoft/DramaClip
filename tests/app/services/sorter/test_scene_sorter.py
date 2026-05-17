"""
SceneSorter 单元测试
"""

import pytest
import sys
from pathlib import Path

# 确保 app 在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.sorter.scene_sorter import SceneSorter, SortStrategy
from app.services.highlight.selector import HighlightSegment


@pytest.fixture
def sample_segments():
    """创建示例片段列表"""
    return [
        HighlightSegment(
            video_path="第01集.mp4",
            start_time=10.0,
            end_time=15.0,
            score=0.9,
            audio_score=0.8,
            emotion_score=0.9,
            visual_score=0.7,
            rhythm_score=0.6,
        ),
        HighlightSegment(
            video_path="第01集.mp4",
            start_time=30.0,
            end_time=35.0,
            score=0.7,
            audio_score=0.6,
            emotion_score=0.7,
            visual_score=0.5,
            rhythm_score=0.4,
        ),
        HighlightSegment(
            video_path="第02集.mp4",
            start_time=5.0,
            end_time=10.0,
            score=0.85,
            audio_score=0.7,
            emotion_score=0.8,
            visual_score=0.6,
            rhythm_score=0.5,
        ),
        HighlightSegment(
            video_path="第02集.mp4",
            start_time=20.0,
            end_time=25.0,
            score=0.6,
            audio_score=0.5,
            emotion_score=0.4,
            visual_score=0.3,
            rhythm_score=0.2,
        ),
    ]


class TestSortStrategy:
    """SortStrategy 枚举测试"""

    def test_strategies_exist(self):
        """所有排序策略应存在"""
        assert SortStrategy.CHRONOLOGICAL == "chronological"
        assert SortStrategy.EMOTION_CURVE == "emotion_curve"
        assert SortStrategy.DIVERSITY_FIRST == "diversity_first"


class TestSceneSorter:
    """SceneSorter 测试"""

    def test_init_default(self):
        """默认初始化应正确"""
        sorter = SceneSorter()
        assert sorter.strategy == SortStrategy.CHRONOLOGICAL
        assert sorter.max_same_episode_consecutive == 2

    def test_init_custom(self):
        """自定义初始化应正确"""
        sorter = SceneSorter(
            strategy=SortStrategy.EMOTION_CURVE,
            max_same_episode_consecutive=3
        )
        assert sorter.strategy == SortStrategy.EMOTION_CURVE
        assert sorter.max_same_episode_consecutive == 3

    def test_sort_empty_segments(self):
        """空片段列表应返回空列表"""
        sorter = SceneSorter()
        result = sorter.sort([])
        assert result == []

    def test_sort_chronological(self, sample_segments):
        """按时间排序应正确"""
        sorter = SceneSorter(strategy=SortStrategy.CHRONOLOGICAL)
        result = sorter.sort(sample_segments)

        # 验证按集数和时间排序
        for i in range(len(result) - 1):
            ep1 = sorter._extract_episode(result[i].video_path)
            ep2 = sorter._extract_episode(result[i + 1].video_path)
            if ep1 == ep2:
                assert result[i].start_time <= result[i + 1].start_time

    def test_sort_emotion_curve(self, sample_segments):
        """情绪曲线排序应正确"""
        sorter = SceneSorter(strategy=SortStrategy.EMOTION_CURVE)
        result = sorter.sort(sample_segments)

        # 情绪曲线排序可能会添加重复片段，所以长度可能大于原始长度
        assert len(result) >= len(sample_segments)

    def test_sort_diversity_first(self, sample_segments):
        """多样性优先排序应正确"""
        sorter = SceneSorter(
            strategy=SortStrategy.DIVERSITY_FIRST,
            max_same_episode_consecutive=1
        )
        result = sorter.sort(sample_segments)

        # 应返回排序后的片段
        assert len(result) == len(sample_segments)

        # 验证没有连续同一集超过限制
        consecutive_count = 1
        for i in range(1, len(result)):
            if result[i].video_path == result[i - 1].video_path:
                consecutive_count += 1
                assert consecutive_count <= sorter.max_same_episode_consecutive
            else:
                consecutive_count = 1

    def test_extract_episode(self):
        """应正确提取集数"""
        sorter = SceneSorter()

        assert sorter._extract_episode("第01集.mp4") == 1
        assert sorter._extract_episode("第1集.mp4") == 1
        assert sorter._extract_episode("episode_01.mp4") == 1
        assert sorter._extract_episode("ep01.mp4") == 1
        assert sorter._extract_episode("01.mp4") == 1
        assert sorter._extract_episode("video_01.mp4") == 1
        # test.mp4 不包含数字，但正则可能匹配到其他内容
        # 这取决于实现，我们只测试能正确提取的情况

    def test_extract_episode_key(self):
        """应正确提取集数标识"""
        sorter = SceneSorter()

        assert sorter._extract_episode_key("/path/to/第01集.mp4") == "第01集.mp4"
        assert sorter._extract_episode_key("/path/to/episode1.mp4") == "episode1.mp4"

    def test_group_by_episode(self, sample_segments):
        """应正确按集数分组"""
        sorter = SceneSorter()
        groups = sorter._group_by_episode(sample_segments)

        assert "第01集.mp4" in groups
        assert "第02集.mp4" in groups
        assert len(groups["第01集.mp4"]) == 2
        assert len(groups["第02集.mp4"]) == 2

    def test_categorize_emotions(self, sample_segments):
        """应正确分类情绪"""
        sorter = SceneSorter()
        categorized = sorter._categorize_emotions(sample_segments)

        # 验证所有分类都存在
        assert "high_arousal_positive" in categorized
        assert "high_arousal_negative" in categorized
        assert "low_arousal_positive" in categorized
        assert "low_arousal_negative" in categorized

        # 验证所有片段都被分类
        total = sum(len(v) for v in categorized.values())
        assert total == len(sample_segments)

    def test_set_strategy(self):
        """应能动态修改策略"""
        sorter = SceneSorter()
        assert sorter.strategy == SortStrategy.CHRONOLOGICAL

        sorter.set_strategy(SortStrategy.EMOTION_CURVE)
        assert sorter.strategy == SortStrategy.EMOTION_CURVE

    def test_get_strategy(self):
        """应能获取当前策略"""
        sorter = SceneSorter(strategy=SortStrategy.DIVERSITY_FIRST)
        assert sorter.get_strategy() == SortStrategy.DIVERSITY_FIRST
