"""engines.narration.modes_w5：交叉解说与超短悬念版编排。"""

from __future__ import annotations

from dramaclip.engines.narration.models import StrategySpec
from dramaclip.engines.narration.modes_w5 import build_cross, build_ultra_short
from dramaclip.engines.semantic.models import ConflictScore
from tests.engines.narration.conftest import assert_slots_paired

_STRATEGY = StrategySpec(min_duration_s=10, max_duration_s=120)


def _scenes() -> list[ConflictScore]:
    return [
        ConflictScore(scene_index=index, start=index * 20.0, end=index * 20.0 + 15.0, score=score)
        for index, score in enumerate([60, 85, 45, 90, 55, 75, 40, 95])
    ]


def test_cross_alternates_original_and_narration() -> None:
    plan = build_cross("ep1", _scenes(), _STRATEGY)
    assert plan.mode == "cross_narration"
    audios = [segment.audio for segment in plan.timeline]
    assert audios[0] == "original"
    assert "narration" in audios
    # 旁白段数量与文案段一致
    narration_count = audios.count("narration")
    assert len(plan.narration_texts) == narration_count
    assert_slots_paired(plan, "cross_narration")
    # 每段旁白都有文案 id 对应（cross-N 顺序与时间轴 narration 段顺序一致）
    ids = [text.id for text in plan.narration_texts]
    assert ids == [f"cross-{i + 1}" for i in range(narration_count)]


def test_cross_respects_duration_budget() -> None:
    strategy = StrategySpec(min_duration_s=10, max_duration_s=60)
    plan = build_cross("ep1", _scenes(), strategy)
    total = sum(segment.end - segment.start for segment in plan.timeline)
    assert total <= 60 + 4 * 6, "预算截断（含旁白估算段）"


def test_ultra_short_structure() -> None:
    plan = build_ultra_short("ep1", _scenes(), _STRATEGY)
    assert plan.mode == "ultra_short_hook"
    assert [segment.audio for segment in plan.timeline] == ["narration", "original", "narration"]
    assert [t.id for t in plan.narration_texts] == ["hook-1", "cta-1"]
    assert_slots_paired(plan, "ultra_short_hook")
    # 三段全部来自冲突分最高的场景（score=95, index=7, start=140）
    best_start = 140.0
    for segment in plan.timeline:
        assert segment.start >= best_start - 0.01


def test_ultra_short_empty_scenes() -> None:
    plan = build_ultra_short("ep1", [], _STRATEGY)
    assert plan.timeline == []
