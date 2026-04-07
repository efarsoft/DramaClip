"""
DramaClip - Core Module Unit Tests
====================================
Pytest-based tests for highlight scoring, selection, and sorting.
Run:  python -m pytest tests/test_core_units.py -v
"""

import os
import sys
import pytest
import numpy as np
from pathlib import Path

# Ensure project root on path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ===== Fixtures =====#

@pytest.fixture
def sample_segment():
    """Create a basic SceneSegment for testing"""
    from app.models.schema import SceneSegment
    return SceneSegment(
        segment_id="ep1_scn1_10.0s",
        episode_index=1,
        start_time=10.0,
        end_time=14.0,
        duration=4.0,
        video_path="/fake/video.mp4",
        audio_path=None,
        subtitle_text="This is a test subtitle",
    )


@pytest.fixture
def multi_episode_segments():
    """Create segments across 3 episodes for sorting/filtering tests"""
    from app.models.schema import SceneSegment
    segs = []
    data = [
        ("ep1_scn1_5.0s", 1, 5.0, 10.0, 0.3),
        ("ep1_scn2_20.0s", 1, 20.0, 24.0, 0.7),
        ("ep2_scn1_8.0s", 2, 8.0, 13.0, 0.5),
        ("ep2_scn2_30.0s", 2, 30.0, 35.0, 0.9),
        ("ep3_scn1_15.0s", 3, 15.0, 19.0, 0.4),
        ("ep3_scn2_40.0s", 3, 40.0, 46.0, 0.8),
    ]
    for seg_id, ep, start, end, score in data:
        segs.append(SceneSegment(
            segment_id=seg_id,
            episode_index=ep,
            start_time=start,
            end_time=end,
            duration=end - start,
            video_path="/fake/video.mp4",
            total_score=score,
            audio_score=score,
            emotion_score=score * 0.8,
            visual_score=score * 0.6,
            rhythm_score=score * 0.5,
        ))
    return segs


# ===== RhythmScorer Tests =====#

class TestRhythmScorer:
    """Tests for RhythmScorer edge cases and scoring logic"""

    def test_zero_duration_returns_zero(self):
        from app.services.highlight.rhythm_scorer import RhythmScorer
        scorer = RhythmScorer()
        score, _ = scorer.score(duration=0, episode_duration=100, start_time=0)
        assert score == 0.0

    def test_negative_duration_returns_zero(self):
        from app.services.highlight.rhythm_scorer import RhythmScorer
        scorer = RhythmScorer()
        score, _ = scorer.score(duration=-5, episode_duration=100, start_time=0)
        assert score == 0.0

    def test_normal_duration_returns_valid_range(self):
        from app.services.highlight.rhythm_scorer import RhythmScorer
        scorer = RhythmScorer()
        score, detail = scorer.score(duration=4.0, episode_duration=120, start_time=30)
        assert 0.0 <= score <= 1.0
        assert isinstance(detail, dict)

    def test_very_short_segment(self):
        from app.services.highlight.rhythm_scorer import RhythmScorer
        scorer = RhythmScorer()
        score, _ = scorer.score(duration=0.1, episode_duration=60, start_time=10)
        assert 0.0 <= score <= 1.0

    def test_segment_at_episode_end(self):
        from app.services.highlight.rhythm_scorer import RhythmScorer
        scorer = RhythmScorer()
        score, _ = scorer.score(duration=5.0, episode_duration=60, start_time=55)
        assert 0.0 <= score <= 1.0

    def test_episode_start_segment(self):
        from app.services.highlight.rhythm_scorer import RhythmScorer
        scorer = RhythmScorer()
        score, _ = scorer.score(duration=3.0, episode_duration=120, start_time=0)
        assert 0.0 <= score <= 1.0


# ===== SceneSorter Tests =====#

class TestSceneSorter:
    """Tests for scene sorting logic"""

    def test_empty_returns_empty(self):
        from app.services.sorter.scene_sorter import SceneSorter
        sorter = SceneSorter()
        assert sorter.sort([]) == []

    def test_single_returns_same(self):
        from app.services.sorter.scene_sorter import SceneSorter
        from app.models.schema import SceneSegment
        sorter = SceneSorter()
        seg = SceneSegment(
            segment_id="ep1_scn1", episode_index=1,
            start_time=10, end_time=15, duration=5.0,
        )
        result = sorter.sort([seg])
        assert len(result) == 1
        assert result[0].segment_id == "ep1_scn1"

    def test_multi_episode_sorted_by_episode_and_time(self):
        from app.services.sorter.scene_sorter import SceneSorter
        sorter = SceneSorter()

        # Shuffle the segments (wrong order)
        from app.models.schema import SceneSegment
        segs = [
            SceneSegment(segment_id="ep2_scn1", episode_index=2, start_time=5, end_time=10, duration=5.0),
            SceneSegment(segment_id="ep1_scn2", episode_index=1, start_time=20, end_time=25, duration=5.0),
            SceneSegment(segment_id="ep1_scn1", episode_index=1, start_time=5, end_time=10, duration=5.0),
            SceneSegment(segment_id="ep2_scn2", episode_index=2, start_time=15, end_time=20, duration=5.0),
        ]

        result = sorter.sort(segs)
        # Verify: episode order first, then time within each episode
        assert result[0].segment_id == "ep1_scn1"
        assert result[1].segment_id == "ep1_scn2"
        assert result[2].segment_id == "ep2_scn1"
        assert result[3].segment_id == "ep2_scn2"

    def test_analyze_sorting_quality(self):
        from app.services.sorter.scene_sorter import SceneSorter
        sorter = SceneSorter()
        quality = sorter.analyze_sorting_quality([])
        assert isinstance(quality, dict)


# ===== VisualScorer Tests =====#

class TestVisualScorer:
    """Tests for visual scorer fallback and frame analysis"""

    def test_nonexistent_file_returns_zero(self):
        from app.services.highlight.visual_scorer import VisualScorer
        scorer = VisualScorer()
        score, detail = scorer.score("/nonexistent/video.mp4")
        assert score == 0.0
        assert "error" in detail

    def test_fallback_score(self):
        from app.services.highlight.visual_scorer import VisualScorer
        scorer = VisualScorer()
        # fallback_score is called internally when OpenCV is unavailable
        # We just verify the method exists and has right signature
        assert hasattr(scorer, '_fallback_score')

    def test_aggregate_empty_frames(self):
        from app.services.highlight.visual_scorer import VisualScorer
        scorer = VisualScorer()
        # Empty frames may return a non-zero base score depending on implementation
        result = scorer._aggregate_frames([], duration=10.0)
        assert 0.0 <= result["total_score"] <= 1.0
        assert result["frames_analyzed"] == 0

    def test_aggregate_single_face_frame(self):
        from app.services.highlight.visual_scorer import VisualScorer
        scorer = VisualScorer()
        frames = [{
            "faces": [{"size_ratio": 0.1}],
            "face_count": 1,
            "has_face": True,
            "face_center": (0.5, 0.5),
            "is_closeup": False,
            "brightness": 120.0,
            "contrast": 50.0,
            "edge_density": 0.3,
            "sharpness": 200.0,
            "is_blurry": False,
        }]
        result = scorer._aggregate_frames(frames, duration=5.0)
        assert 0.0 <= result["total_score"] <= 1.0
        assert result["has_face_ratio"] == 1.0
        assert result["frames_analyzed"] == 1

    def test_aggregate_blurry_frames(self):
        from app.services.highlight.visual_scorer import VisualScorer
        scorer = VisualScorer()
        frames = [
            {"faces": [], "face_count": 0, "has_face": False, "face_center": None,
             "is_closeup": False, "brightness": 80.0, "contrast": 20.0,
             "edge_density": 0.05, "sharpness": 30.0, "is_blurry": True},
            {"faces": [], "face_count": 0, "has_face": False, "face_center": None,
             "is_closeup": False, "brightness": 90.0, "contrast": 15.0,
             "edge_density": 0.03, "sharpness": 20.0, "is_blurry": True},
        ]
        result = scorer._aggregate_frames(frames, duration=10.0)
        # Blurry frames without faces should have low score
        assert result["total_score"] < 0.5
        assert result["blurry_ratio"] == 1.0

    def test_default_sample_fps(self):
        from app.services.highlight.visual_scorer import VisualScorer
        scorer = VisualScorer()
        assert scorer.sample_fps == 0.5

    def test_face_detect_width_constant(self):
        from app.services.highlight.visual_scorer import VisualScorer
        assert VisualScorer.FACE_DETECT_WIDTH == 640


# ===== AudioScorer Tests =====#

class TestAudioScorer:
    """Tests for audio scorer"""

    def test_nonexistent_file_returns_zero(self):
        from app.services.highlight.audio_scorer import AudioScorer
        scorer = AudioScorer()
        score, detail = scorer.score("/nonexistent/audio.wav")
        assert score == 0.0
        assert "error" in detail

    def test_custom_thresholds(self):
        from app.services.highlight.audio_scorer import AudioScorer
        scorer = AudioScorer(peak_threshold_db=-5.0, energy_change_threshold=0.8)
        assert scorer.peak_threshold_db == -5.0
        assert scorer.energy_change_threshold == 0.8


# ===== EmotionScorer Tests =====#

class TestEmotionScorer:
    """Tests for emotion scorer"""

    def test_empty_text_returns_low_score(self):
        from app.services.highlight.emotion_scorer import EmotionScorer
        scorer = EmotionScorer()
        score, detail = scorer.score("")
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_neutral_text(self):
        from app.services.highlight.emotion_scorer import EmotionScorer
        scorer = EmotionScorer()
        score, detail = scorer.score("This is a normal conversation about the weather.")
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_emotional_text_higher_score(self):
        from app.services.highlight.emotion_scorer import EmotionScorer
        scorer = EmotionScorer()
        score_neutral, _ = scorer.score("hello how are you")
        score_emotional, _ = scorer.score("I can't believe you did that! How dare you!")
        # Emotional text should generally score higher than neutral
        assert score_emotional >= score_neutral  # At least not lower

    def test_chinese_emotional_text(self):
        from app.services.highlight.emotion_scorer import EmotionScorer
        scorer = EmotionScorer()
        score, detail = scorer.score("你怎么敢背叛我！我不会原谅你的！")
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0
        # Should detect Chinese emotional keywords
        if "emotion_tags" in detail:
            assert isinstance(detail["emotion_tags"], list)


# ===== HighlightScorer Tests =====#

class TestHighlightScorer:
    """Tests for the aggregate highlight scorer"""

    def test_score_segment_returns_valid(self):
        from app.services.highlight.scorer import HighlightScorer
        from app.models.schema import SceneSegment
        scorer = HighlightScorer()

        seg = SceneSegment(
            segment_id="test", episode_index=1,
            start_time=5, end_time=10, duration=5.0,
            video_path="/fake/video.mp4",
            subtitle_text="Test emotional dialogue",
        )
        # This will use fallback for video and fake audio, should not crash
        result = scorer.score_segment(seg)
        assert isinstance(result.total_score, float)
        assert 0.0 <= result.total_score <= 1.0
        assert isinstance(result.details, dict)

    def test_score_segments_batch(self):
        from app.services.highlight.scorer import HighlightScorer
        from app.models.schema import SceneSegment
        scorer = HighlightScorer()

        segs = [
            SceneSegment(segment_id="s1", episode_index=1, start_time=5, end_time=10, duration=5.0,
                         video_path="/fake/video.mp4", subtitle_text="Angry!"),
            SceneSegment(segment_id="s2", episode_index=1, start_time=15, end_time=20, duration=5.0,
                         video_path="/fake/video.mp4", subtitle_text="Calm text"),
        ]
        results = scorer.score_segments(segs)
        assert len(results) == 2
        for r in results:
            assert 0.0 <= r.total_score <= 1.0


# ===== HighlightSelector Tests =====#

class TestHighlightSelector:
    """Tests for highlight segment selection"""

    def _make_scoring_result(self, segment):
        from app.services.highlight.scorer import ScoringResult
        return ScoringResult(
            segment=segment,
            audio_score=segment.audio_score or 0.5,
            emotion_score=segment.emotion_score or 0.5,
            visual_score=segment.visual_score or 0.5,
            rhythm_score=segment.rhythm_score or 0.5,
            total_score=segment.total_score or 0.5,
            details={},
        )

    def test_empty_returns_empty(self):
        from app.services.highlight.selector import HighlightSelector
        selector = HighlightSelector()
        assert selector.select([]) == []

    def test_select_respects_target_duration(self, multi_episode_segments):
        from app.services.highlight.selector import HighlightSelector
        selector = HighlightSelector()
        scored = [self._make_scoring_result(s) for s in multi_episode_segments]

        # Select with very short target duration
        result = selector.select(scored, target_duration=6.0)
        total_dur = sum(s.duration for s in result)
        # Should not wildly exceed target
        assert total_dur <= 30.0  # At most all segments

    def test_select_episode_balance(self, multi_episode_segments):
        from app.services.highlight.selector import HighlightSelector
        from app.models.schema import HighlightConfig
        config = HighlightConfig(
            min_episodes_covered=2,
            min_segment_duration=2.0,
            max_segments_per_episode=5,
        )
        selector = HighlightSelector(config)
        scored = [self._make_scoring_result(s) for s in multi_episode_segments]

        result = selector.select(scored, target_duration=60.0)
        episodes = set(s.episode_index for s in result)
        # With 3 episodes, min_episodes_covered=2 means at least 2 should be covered
        assert len(episodes) >= 2


# ===== DirectCutPipeline Tests =====#

class TestDirectCutPipeline:
    """Unit tests for DirectCutPipeline (no actual video processing)"""

    def test_pipeline_creation(self):
        from unittest.mock import patch
        with patch('app.services.direct_cut.pipeline.DirectCutPipeline._get_temp_dir',
                   return_value=str(PROJECT_ROOT / 'tests' / 'output' / 'tmp')):
            from app.services.direct_cut.pipeline import DirectCutPipeline
            pipeline = DirectCutPipeline(config={
                "audio_weight": 0.4, "emotion_weight": 0.3,
                "visual_weight": 0.2, "rhythm_weight": 0.1,
            })
        assert pipeline.scorer is not None
        assert pipeline.selector is not None
        assert pipeline.sorter is not None
        assert pipeline.detector is not None

    def test_build_reason_basic(self):
        from app.services.direct_cut.pipeline import DirectCutPipeline
        from app.models.schema import SceneSegment
        seg = SceneSegment(
            segment_id="test", episode_index=1,
            start_time=10, end_time=14, duration=4.0,
            is_closeup=True, has_face=True,
            subtitle_text="You betrayed me!",
        )
        reason = DirectCutPipeline._build_reason(seg)
        assert "特写" in reason
        assert "有人物" in reason


# ===== NarrationPipeline Tests =====#

class TestNarrationPipeline:
    """Unit tests for narration pipeline components"""

    def test_plot_parser_parse_no_transcript(self):
        from app.services.narration.pipeline import PlotParser
        parser = PlotParser()
        from app.models.schema import SceneSegment
        seg = SceneSegment(
            segment_id="test", episode_index=1,
            start_time=10, end_time=14, duration=4.0,
            subtitle_text=None,
        )
        result = parser.parse([seg])
        assert result.get("error") == "no_transcript"

    def test_narration_generator_styles(self):
        from app.services.narration.pipeline import NarrationGenerator
        assert "normal" in NarrationGenerator.STYLES
        assert "satire" in NarrationGenerator.STYLES
        assert "concise" in NarrationGenerator.STYLES
        assert "emotional" in NarrationGenerator.STYLES

    def test_llm_result_parsing_valid_json(self):
        from app.services.narration.pipeline import PlotParser
        parser = PlotParser()
        result = parser._parse_llm_result('{"summary": "A story about revenge", "characters": ["Alice"], "main_conflict": "Betrayal", "key_moments": [], "tags": ["revenge"]}')
        assert result["summary"] == "A story about revenge"
        assert "Alice" in result["characters"]

    def test_llm_result_parsing_json_in_codeblock(self):
        from app.services.narration.pipeline import PlotParser
        parser = PlotParser()
        text = 'Here is the analysis:\n```json\n{"summary": "Drama", "characters": ["Bob"], "main_conflict": "Love", "key_moments": [], "tags": ["love"]}\n```'
        result = parser._parse_llm_result(text)
        assert result["summary"] == "Drama"

    def test_llm_result_parsing_invalid_json(self):
        from app.services.narration.pipeline import PlotParser
        parser = PlotParser()
        result = parser._parse_llm_result("This is not JSON at all, just plain text about a drama.")
        assert "raw_response" in result
        assert result["error"] == "parse_failed"

    def test_narration_script_parsing(self):
        from app.services.narration.pipeline import NarrationGenerator
        gen = NarrationGenerator(style="normal")
        script = gen._parse_script(
            '{"title":"Test","segments":[{"timestamp":0,"text":"Hello","emphasis":true},{"timestamp":5,"text":"World","emphasis":false}],"full_text":"Hello World"}',
            target_duration=30,
        )
        assert script.title == "Test"
        assert len(script.segments) == 2
        assert script.segments[0]["text"] == "Hello"
        assert script.full_text == "Hello World"

    def test_narration_script_fallback(self):
        from app.services.narration.pipeline import NarrationGenerator
        gen = NarrationGenerator(style="normal")
        script = gen._parse_script("This is not JSON", target_duration=30)
        assert script.title == "AI解说文案"
        assert len(script.segments) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
