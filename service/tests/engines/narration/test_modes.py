"""engines.narration.modes：编排纯函数。"""

from __future__ import annotations

from dramaclip.engines.narration.models import StrategySpec
from dramaclip.engines.narration.modes import build_intro, build_raw_clip
from dramaclip.engines.semantic.models import ConflictScore, HighlightSegment
from tests.engines.narration.conftest import assert_slots_paired

_STRATEGY = StrategySpec(min_duration_s=10, max_duration_s=30)


def _scenes() -> list[ConflictScore]:
    return [
        ConflictScore(scene_index=0, start=0, end=6, score=80),
        ConflictScore(scene_index=1, start=6, end=12, score=40),
        ConflictScore(scene_index=2, start=12, end=18, score=85),
        ConflictScore(scene_index=3, start=18, end=24, score=50),
        ConflictScore(scene_index=4, start=24, end=30, score=90),
        ConflictScore(scene_index=5, start=30, end=36, score=45),
        ConflictScore(scene_index=6, start=36, end=42, score=72),
    ]


def test_raw_clip_opens_with_highest_conflict() -> None:
    plan = build_raw_clip("ep1", _scenes(), [], _STRATEGY)
    assert plan.mode == "raw_clip"
    assert plan.timeline[0].start == 24 and plan.timeline[0].end == 30, "开场应为冲突最高场景"
    starts = [seg.start for seg in plan.timeline[1:]]
    assert starts == sorted(starts), "开场预告式前置，其余按原片时间线"
    total = sum(seg.end - seg.start for seg in plan.timeline)
    assert total <= _STRATEGY.max_duration_s + 12, "截断预算（含首尾豁免）"


def test_raw_clip_all_original_audio() -> None:
    plan = build_raw_clip("ep1", _scenes(), [], _STRATEGY)
    assert all(seg.audio == "original" for seg in plan.timeline)


def test_intro_marks_first_segment_as_narration() -> None:
    plan = build_intro("ep1", _scenes(), _STRATEGY)
    assert plan.mode == "intro_narration"
    assert_slots_paired(plan, "intro_narration")
    assert plan.timeline[0].narration_id == "intro-1"
    assert plan.timeline[0].audio == "narration"
    assert plan.timeline[0].end - plan.timeline[0].start <= 30
    assert all(seg.audio == "original" for seg in plan.timeline[1:])


def test_intro_empty_scenes() -> None:
    """无素材 ⇒ 无槽位：否则等于叫编剧对着空时间轴凭空写。"""
    plan = build_intro("ep1", [], _STRATEGY)
    assert plan.timeline == [] and plan.narration_texts == []


def test_highlights_not_required() -> None:
    plan = build_raw_clip("ep1", _scenes(), [HighlightSegment(start=0, end=6, score=80)], _STRATEGY)
    assert plan.timeline
