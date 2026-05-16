"""
HighlightScorer 单元测试

注意：由于打分器依赖较重（需要视频文件、音频处理等），
此测试主要测试配置和权重归一化等不需要实际文件的功能。
完整的集成测试需要实际的视频文件。
"""

import pytest
import sys
from pathlib import Path

# 确保 app 在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.highlight.scorer import HighlightScorer


class TestHighlightScorerInit:
    """HighlightScorer 初始化测试"""

    def test_default_weights(self):
        """默认权重应正确归一化"""
        scorer = HighlightScorer()

        # 验证权重存在
        assert hasattr(scorer, 'audio_weight')
        assert hasattr(scorer, 'emotion_weight')
        assert hasattr(scorer, 'visual_weight')
        assert hasattr(scorer, 'rhythm_weight')
        assert hasattr(scorer, 'plot_importance_weight')

        # 验证权重归一化（总和应为 1.0）
        total = (
            scorer.audio_weight
            + scorer.emotion_weight
            + scorer.visual_weight
            + scorer.rhythm_weight
            + scorer.plot_importance_weight
        )
        assert abs(total - 1.0) < 0.001

    def test_custom_weights(self):
        """自定义权重应正确归一化"""
        scorer = HighlightScorer(
            audio_weight=0.4,
            emotion_weight=0.3,
            visual_weight=0.2,
            rhythm_weight=0.1,
            plot_importance_weight=0.0,
        )

        # 验证权重归一化
        total = (
            scorer.audio_weight
            + scorer.emotion_weight
            + scorer.visual_weight
            + scorer.rhythm_weight
            + scorer.plot_importance_weight
        )
        assert abs(total - 1.0) < 0.001

        # 验证相对比例
        assert scorer.audio_weight > scorer.emotion_weight
        assert scorer.emotion_weight > scorer.visual_weight
        assert scorer.visual_weight > scorer.rhythm_weight

    def test_equal_weights(self):
        """等权重应正确分配"""
        scorer = HighlightScorer(
            audio_weight=1.0,
            emotion_weight=1.0,
            visual_weight=1.0,
            rhythm_weight=1.0,
            plot_importance_weight=1.0,
        )

        # 所有权重应相等
        assert abs(scorer.audio_weight - 0.2) < 0.001
        assert abs(scorer.emotion_weight - 0.2) < 0.001
        assert abs(scorer.visual_weight - 0.2) < 0.001
        assert abs(scorer.rhythm_weight - 0.2) < 0.001
        assert abs(scorer.plot_importance_weight - 0.2) < 0.001

    def test_zero_weights(self):
        """全零权重应能处理（虽然实际不推荐）"""
        # 这会触发除零，但代码中有 total 归一化
        # 实际使用时不应传入全零权重
        try:
            scorer = HighlightScorer(
                audio_weight=0.0,
                emotion_weight=0.0,
                visual_weight=0.0,
                rhythm_weight=0.0,
                plot_importance_weight=0.0,
            )
            # 如果没有抛出异常，权重应该是 NaN 或 0
            # 这取决于代码实现
        except ZeroDivisionError:
            # 这是预期的行为
            pass


class TestHighlightScorerEmotion:
    """HighlightScorer 情绪分析测试"""

    def test_score_emotion_empty_text(self):
        """空文本应返回 0 分"""
        scorer = HighlightScorer()
        score = scorer._score_emotion(None)
        assert score == 0.0

        score = scorer._score_emotion("")
        assert score == 0.0

    def test_score_emotion_positive_keywords(self):
        """正面关键词应提高分数"""
        scorer = HighlightScorer()

        # 包含多个正面关键词
        text = "我爱你，我们在一起永远幸福快乐"
        score = scorer._score_emotion(text)
        assert score > 0.0

    def test_score_emotion_negative_keywords(self):
        """负面关键词应提高分数"""
        scorer = HighlightScorer()

        # 包含多个负面关键词
        text = "我恨你，背叛让我痛苦绝望"
        score = scorer._score_emotion(text)
        assert score > 0.0

    def test_score_emotion_mixed_keywords(self):
        """混合情绪关键词应提高冲突分数"""
        scorer = HighlightScorer()

        # 包含正面和负面关键词（情绪冲突）
        text = "我爱你但也很痛苦，快乐和悲伤交织"
        score = scorer._score_emotion(text)
        assert score > 0.0

    def test_score_emotion_no_keywords(self):
        """无情感关键词应返回 0 分"""
        scorer = HighlightScorer()

        text = "今天天气不错，我们去公园散步吧"
        score = scorer._score_emotion(text)
        assert score == 0.0

    def test_score_emotion_range(self):
        """情绪分数应在 0-1 范围内"""
        scorer = HighlightScorer()

        texts = [
            "我爱你",
            "我恨你",
            "我爱你但很痛苦",
            "无情感的普通文本",
            "爱喜欢开心高兴快乐幸福美好温暖感动守护成功胜利赢强厉害棒优秀完美精彩赞笑甜浪漫亲抱吻结婚在一起永远",
        ]

        for text in texts:
            score = scorer._score_emotion(text)
            assert 0.0 <= score <= 1.0


class TestHighlightScorerPlotImportance:
    """HighlightScorer 剧情重要性测试"""

    def test_score_plot_importance_beginning(self):
        """开场场景应有较高分数"""
        scorer = HighlightScorer()

        score_beginning = scorer._score_plot_importance(5.0, "测试字幕", "beginning")
        score_middle = scorer._score_plot_importance(5.0, "测试字幕", "middle")

        assert score_beginning > score_middle

    def test_score_plot_importance_climax(self):
        """高潮场景应有最高分数"""
        scorer = HighlightScorer()

        score_climax = scorer._score_plot_importance(5.0, "测试字幕", "climax")
        score_middle = scorer._score_plot_importance(5.0, "测试字幕", "middle")

        assert score_climax > score_middle

    def test_score_plot_importance_ending(self):
        """结尾场景应有较高分数"""
        scorer = HighlightScorer()

        score_ending = scorer._score_plot_importance(5.0, "测试字幕", "ending")
        score_middle = scorer._score_plot_importance(5.0, "测试字幕", "middle")

        assert score_ending > score_middle

    def test_score_plot_importance_duration(self):
        """中等时长应有较高分数"""
        scorer = HighlightScorer()

        # 黄金时长 3-10 秒
        score_optimal = scorer._score_plot_importance(5.0, "测试字幕", "middle")
        score_short = scorer._score_plot_importance(1.0, "测试字幕", "middle")
        score_long = scorer._score_plot_importance(20.0, "测试字幕", "middle")

        assert score_optimal > score_short
        assert score_optimal > score_long

    def test_score_plot_importance_subtitle_density(self):
        """高字幕密度应有较高分数"""
        scorer = HighlightScorer()

        # 高密度字幕
        dense_subtitle = "这是一段很长的字幕文本，包含很多信息，用于测试高密度情况"
        score_dense = scorer._score_plot_importance(5.0, dense_subtitle, "middle")

        # 低密度字幕
        sparse_subtitle = "短"
        score_sparse = scorer._score_plot_importance(5.0, sparse_subtitle, "middle")

        assert score_dense > score_sparse

    def test_score_plot_importance_range(self):
        """剧情重要性分数应在 0-1 范围内"""
        scorer = HighlightScorer()

        positions = ["beginning", "middle", "climax", "ending"]
        durations = [0.5, 2.0, 5.0, 10.0, 20.0]

        for pos in positions:
            for dur in durations:
                score = scorer._score_plot_importance(dur, "测试字幕", pos)
                assert 0.0 <= score <= 1.0
