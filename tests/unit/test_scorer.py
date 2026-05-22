"""HighlightScorer Unit Tests"""

import unittest
from unittest.mock import patch, MagicMock
import numpy as np

from app.services.highlight.scorer import HighlightScorer


class TestHighlightScorer(unittest.TestCase):
    def test_weight_normalization(self):
        # 初始化带非归一化权重的打分器
        scorer = HighlightScorer(
            audio_weight=1.0,
            emotion_weight=1.0,
            visual_weight=1.0,
            rhythm_weight=1.0,
            plot_importance_weight=1.0
        )
        # 总权重是 5.0，归一化后每个权重应该为 0.2
        self.assertAlmostEqual(scorer.audio_weight, 0.2)
        self.assertAlmostEqual(scorer.emotion_weight, 0.2)
        self.assertAlmostEqual(scorer.visual_weight, 0.2)
        self.assertAlmostEqual(scorer.rhythm_weight, 0.2)
        self.assertAlmostEqual(scorer.plot_importance_weight, 0.2)

    def test_score_emotion_empty(self):
        scorer = HighlightScorer()
        self.assertEqual(scorer._score_emotion(None), 0.0)
        self.assertEqual(scorer._score_emotion(""), 0.0)

    def test_score_emotion_neutral(self):
        scorer = HighlightScorer()
        # 没有任何情感关键词的句子
        self.assertEqual(scorer._score_emotion("今天天气很好。"), 0.0)

    def test_score_emotion_positive_and_negative(self):
        scorer = HighlightScorer()
        # 包含情感词的句子
        score_positive = scorer._score_emotion("我们结婚在一起，永远幸福！")
        self.assertGreater(score_positive, 0.0)
        
        score_negative = scorer._score_emotion("这真是太痛苦了，我恨你！")
        self.assertGreater(score_negative, 0.0)

    def test_score_plot_importance(self):
        scorer = HighlightScorer()
        
        # 1. 测试关键场景位置加分
        score_climax = scorer._score_plot_importance(duration=5.0, subtitle_text="这是一个相当长的一段字幕台词了。", scene_position="climax")
        score_middle = scorer._score_plot_importance(duration=5.0, subtitle_text="这是一个相当长的一段字幕台词了。", scene_position="middle")
        self.assertGreater(score_climax, score_middle)

        # 2. 测试黄金时长加分 (3.0 - 10.0 秒)
        score_golden = scorer._score_plot_importance(duration=5.0, subtitle_text=None, scene_position="middle")
        score_too_short = scorer._score_plot_importance(duration=0.5, subtitle_text=None, scene_position="middle")
        self.assertGreater(score_golden, score_too_short)

        # 3. 测试字幕密度加分
        score_high_density = scorer._score_plot_importance(duration=2.0, subtitle_text="这句话真的很长很长很长很长很长很长很长很长很长很长", scene_position="middle")
        score_no_subtitle = scorer._score_plot_importance(duration=2.0, subtitle_text=None, scene_position="middle")
        self.assertGreater(score_high_density, score_no_subtitle)

    @patch("app.services.highlight.scorer.HighlightScorer._score_audio")
    @patch("app.services.highlight.scorer.HighlightScorer._score_emotion")
    @patch("app.services.highlight.scorer.HighlightScorer._score_visual")
    @patch("app.services.highlight.scorer.HighlightScorer._score_rhythm")
    def test_score_integration(self, mock_rhythm, mock_visual, mock_emotion, mock_audio):
        # 模拟各个维度的打分值
        mock_audio.return_value = 0.8
        mock_emotion.return_value = 0.6
        mock_visual.return_value = 0.7
        mock_rhythm.return_value = 0.5

        # 初始化打分器
        scorer = HighlightScorer(
            audio_weight=0.35,
            emotion_weight=0.30,
            visual_weight=0.20,
            rhythm_weight=0.10,
            plot_importance_weight=0.05
        )

        result = scorer.score(
            video_path="dummy_video.mp4",
            subtitle_text="测试字幕内容",
            duration=5.0,
            scene_position="climax"
        )

        # 验证返回结构
        self.assertIn("audio_score", result)
        self.assertIn("emotion_score", result)
        self.assertIn("visual_score", result)
        self.assertIn("rhythm_score", result)
        self.assertIn("plot_importance_score", result)
        self.assertIn("total_score", result)

        # 验证各个分数是否符合预期
        self.assertEqual(result["audio_score"], 0.8)
        self.assertEqual(result["emotion_score"], 0.6)
        self.assertEqual(result["visual_score"], 0.7)
        self.assertEqual(result["rhythm_score"], 0.5)
        
        # 计算预期的剧情重要性分数
        expected_plot_score = scorer._score_plot_importance(5.0, "测试字幕内容", "climax")
        self.assertAlmostEqual(result["plot_importance_score"], expected_plot_score)

        # 验证计算的总加权分数
        expected_total = (
            scorer.audio_weight * 0.8
            + scorer.emotion_weight * 0.6
            + scorer.visual_weight * 0.7
            + scorer.rhythm_weight * 0.5
            + scorer.plot_importance_weight * expected_plot_score
        )
        self.assertAlmostEqual(result["total_score"], expected_total)


if __name__ == "__main__":
    unittest.main()
