"""engines.narration.dialogue_selector：对白打分与编排。"""

from __future__ import annotations

from dramaclip.engines.analysis.models import AsrSegment, AudioFeatures, SpeechZone
from dramaclip.engines.narration.dialogue_selector import (
    build_dialogue,
    score_line,
    select_dialogue_lines,
)
from dramaclip.engines.narration.models import StrategySpec

_STRATEGY = StrategySpec(min_duration_s=10, max_duration_s=60)


def test_score_line_rewards_conflict_and_emotion() -> None:
    calm = score_line("今天天气不错", 3.0)
    angry = score_line("你给我滚！你这个废物！我要报仇！", 4.0)
    assert angry > calm + 30


def test_score_line_penalizes_odd_length() -> None:
    normal = score_line("正常的一句话", 3.0, independent=True)
    tiny = score_line("短", 0.8, independent=True)
    assert normal > tiny


def test_select_dialogue_lines_filters_and_orders() -> None:
    segments = [
        AsrSegment(start=1, end=4, text="你给我滚出去！骗子！"),
        AsrSegment(start=4.2, end=4.6, text="短"),
        AsrSegment(start=10, end=14, text="今天中午吃什么"),
        AsrSegment(start=20, end=26, text="我要报仇！你们都给我等着！"),
    ]
    audio = AudioFeatures(
        speech_zones=[SpeechZone(start=0.5, end=4.5), SpeechZone(start=19.5, end=26.5)]
    )
    picked = select_dialogue_lines(segments, audio)
    texts = [segment.text for segment, _score in picked]
    assert "短" not in "".join(texts)
    assert any("滚出去" in text for text in texts)
    starts = [segment.start for segment, _ in picked]
    assert starts == sorted(starts)


def test_build_dialogue_opens_with_best_and_marks_fades() -> None:
    segments = [
        AsrSegment(start=1, end=4, text="普通对白而已"),
        AsrSegment(start=10, end=15, text="滚！你这个骗子！我要杀了你！"),
        AsrSegment(start=30, end=34, text="真相总会大白的。"),
    ]
    audio = AudioFeatures()
    lines = select_dialogue_lines(segments, audio)
    plan = build_dialogue("ep1", lines, _STRATEGY)

    assert plan.mode == "dialogue_narration"
    assert plan.timeline[0].transition == "cut", "开场硬切"
    assert all(segment.transition == "fade" for segment in plan.timeline[1:])
    assert all(segment.audio == "original" for segment in plan.timeline)
    # 开场应为最高分句（冲突句 10-15s）
    assert plan.timeline[0].start == 10.0


def test_build_dialogue_empty_lines() -> None:
    plan = build_dialogue("ep1", [], _STRATEGY)
    assert plan.timeline == [] and plan.mode == "dialogue_narration"
