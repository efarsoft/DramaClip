"""engines.narration.modes_w8：全片解说编排。"""

from __future__ import annotations

from dramaclip.engines.narration.casting import stamp
from dramaclip.engines.narration.models import StrategySpec
from dramaclip.engines.narration.modes_w8 import build_full
from dramaclip.engines.semantic.models import ConflictScore
from tests.engines.narration.conftest import assert_slots_paired

_STRATEGY = StrategySpec(min_duration_s=10, max_duration_s=120)


def _scenes() -> list[ConflictScore]:
    return [
        ConflictScore(scene_index=index, start=index * 12.0, end=index * 12.0 + 10.0, score=score)
        for index, score in enumerate([60, 85, 45, 90, 55, 75, 40, 95, 50, 65])
    ]


def test_full_covers_timeline_with_ducked_audio() -> None:
    plan = build_full(stamp([(1, "ep1", _scenes())]), _STRATEGY)
    assert plan.mode == "full_narration"
    assert all(segment.audio == "ducked" for segment in plan.timeline)
    starts = [segment.start for segment in plan.timeline]
    assert starts == sorted(starts), "时间线顺序"


def test_full_scene_cap_and_texts() -> None:
    plan = build_full(stamp([(1, "ep1", _scenes())]), _STRATEGY)
    assert len(plan.timeline) <= 8
    assert_slots_paired(plan, "full_narration")


def test_full_slot_briefs_follow_narrative_position() -> None:
    """位置与冲突分决定槽位职责（原模板的位置语义搬到这里，句子本身归编剧）。"""
    plan = build_full(stamp([(1, "ep1", _scenes())]), _STRATEGY)
    texts = plan.narration_texts
    assert texts[0].brief.startswith("开篇")
    assert "高潮" in texts[1].brief, "score>=85 的高潮分支优先于推进分支"
    assert texts[3].brief.startswith("推进")
    assert texts[-1].brief.startswith("收尾")


def test_full_empty_scenes() -> None:
    plan = build_full([], _STRATEGY)
    assert plan.timeline == []
