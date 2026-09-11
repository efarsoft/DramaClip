"""engines.narration.line_scoring：单句对白质量打分。"""

from __future__ import annotations

from dramaclip.engines.narration.line_scoring import score_line


def test_score_line_rewards_conflict_and_emotion() -> None:
    calm = score_line("今天天气不错", 3.0)
    angry = score_line("你给我滚！你这个废物！我要报仇！", 4.0)
    assert angry > calm + 30


def test_score_line_penalizes_odd_length() -> None:
    normal = score_line("正常的一句话", 3.0, independent=True)
    tiny = score_line("短", 0.8, independent=True)
    assert normal > tiny
