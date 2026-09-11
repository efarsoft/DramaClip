"""engines.narration.modes_w5：交叉解说与超短悬念版编排。"""

from __future__ import annotations

from dramaclip.engines.narration.models import StrategySpec
from dramaclip.engines.narration.modes_w5 import build_cross, build_ultra_short
from dramaclip.engines.semantic.models import ConflictScore

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
    assert [t.id for t in plan.narration_texts] == ["hook-1", "cta-1"] and all(
        not t.text for t in plan.narration_texts
    )
    assert all(t.slot and t.window for t in plan.narration_texts), "两个槽位都要有职责与区间"
    assert [s.narration_id for s in plan.timeline if s.narration_id] == ["hook-1", "cta-1"]
    # 三段全部来自冲突分最高的场景（score=95, index=7, start=140）
    best_start = 140.0
    for segment in plan.timeline:
        assert segment.start >= best_start - 0.01


def test_ultra_short_empty_scenes() -> None:
    plan = build_ultra_short("ep1", [], _STRATEGY)
    assert plan.timeline == []


def test_cross_slots_carry_role_and_window() -> None:
    """编排器只负责"这里要说什么"，句子本身归编剧：text 必须为空、槽位信息必须齐。"""
    plan = build_cross("ep1", _scenes(), _STRATEGY)
    assert plan.narration_texts, "至少要有一个旁白槽位"
    for text in plan.narration_texts:
        assert text.text == "", "文案池已删除，编排器不得再自带任何成稿句子"
        assert text.slot, "槽位职责缺失 → 编剧无从下笔"
        assert text.window is not None and text.window[1] > text.window[0]
    by_id = {segment.narration_id: segment for segment in plan.timeline if segment.narration_id}
    assert set(by_id) == {text.id for text in plan.narration_texts}, "段与文案必须按 id 两两配对"
