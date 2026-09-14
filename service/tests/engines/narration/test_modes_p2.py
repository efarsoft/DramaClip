"""engines.narration.modes_p2：双人对谈与内心独白编排。"""

from __future__ import annotations

from dramaclip.engines.narration.casting import stamp
from dramaclip.engines.narration.models import StrategySpec
from dramaclip.engines.narration.modes_p2 import build_dual_host, build_monologue
from dramaclip.engines.semantic.models import ConflictScore
from tests.engines.narration.conftest import assert_slots_paired

_STRATEGY = StrategySpec(min_duration_s=10, max_duration_s=120)


def _scenes() -> list[ConflictScore]:
    return [
        ConflictScore(scene_index=index, start=index * 10.0, end=index * 10.0 + 9.0, score=score)
        for index, score in enumerate([65, 88, 50, 92, 70])
    ]


def test_dual_host_alternates_voices() -> None:
    plan = build_dual_host(stamp([(1, "ep1", _scenes())]), _STRATEGY)
    voices = [text.voice for text in plan.narration_texts]
    assert voices[0] != voices[1], "双音色应交替"
    assert voices[0] == voices[2], "同主持人的音色一致"
    assert all(segment.audio == "narration" for segment in plan.timeline)
    assert_slots_paired(plan, "dual_host_chat")
    assert "主持人 A" in plan.narration_texts[0].brief, "编剧要知道这句该谁开口"
    assert "嘉宾 B" in plan.narration_texts[1].brief


def test_dual_host_empty_safe() -> None:
    plan = build_dual_host([], _STRATEGY)
    assert plan.timeline == [] and plan.narration_texts == []


def test_monologue_first_person_single_voice() -> None:
    plan = build_monologue(stamp([(1, "ep1", _scenes())]), _STRATEGY)
    assert plan.mode == "inner_monologue"
    voices = {text.voice for text in plan.narration_texts}
    assert len(voices) == 1, "内心独白应为单一音色"
    assert all(t.brief.startswith("第一人称") for t in plan.narration_texts), "全程第一人称"
    assert all(segment.audio == "narration" for segment in plan.timeline)
    assert_slots_paired(plan, "inner_monologue")
