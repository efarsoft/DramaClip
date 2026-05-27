"""HighlightSelector Safety Unit Tests"""

import unittest
from app.services.highlight.selector import HighlightSelector


class TestHighlightSelectorSafety(unittest.TestCase):
    def test_select_from_scores_with_nones(self):
        selector = HighlightSelector()
        
        # Test scored_segments containing explicit None values
        scored_segments = [
            {
                "audio_score": None,
                "emotion_score": 0.8,
                "visual_score": None,
                "rhythm_score": 0.5,
                "total_score": None
            },
            {
                "audio_score": 0.9,
                "emotion_score": None,
                "visual_score": 0.4,
                "rhythm_score": None,
                "total_score": None
            }
        ]
        
        video_paths = ["dummy1.mp4", "dummy2.mp4"]
        start_times = [0.0, 5.0]
        end_times = [3.0, 8.0]
        subtitle_texts = ["Hello", "World"]

        # This should execute and complete successfully without raising any TypeError
        results = selector.select_from_scores(
            scored_segments=scored_segments,
            video_paths=video_paths,
            start_times=start_times,
            end_times=end_times,
            subtitle_texts=subtitle_texts,
        )

        self.assertIsNotNone(results)
        self.assertGreater(len(results), 0)
        
        for segment in results:
            self.assertIsInstance(segment.audio_score, float)
            self.assertIsInstance(segment.emotion_score, float)
            self.assertIsInstance(segment.visual_score, float)
            self.assertIsInstance(segment.rhythm_score, float)
            self.assertIsInstance(segment.score, float)
            self.assertIsNotNone(segment.reason)


if __name__ == "__main__":
    unittest.main()
