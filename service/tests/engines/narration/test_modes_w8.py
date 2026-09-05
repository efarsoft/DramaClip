"""engines.narration.modes_w8：全片解说编排。"""

from __future__ import annotations

from dramaclip.engines.narration.models import StrategySpec
from dramaclip.engines.narration.modes_w8 import build_full, narration_texts_for
from dramaclip.engines.semantic.models import ConflictScore

_STRATEGY = StrategySpec(min_duration_s=10, max_duration_s=120)


def _scenes() -> list[ConflictScore]:
    return [
        ConflictScore(scene_index=index, start=index * 12.0, end=index * 12.0 + 10.0, score=score)
        for index, score in enumerate([60, 85, 45, 90, 55, 75, 40, 95, 50, 65])
    ]


def test_full_covers_timeline_with_ducked_audio() -> None:
    plan = build_full("ep1", _scenes(), _STRATEGY, "透视眼", genre="逆袭")
    assert plan.mode == "full_narration"
    assert all(segment.audio == "ducked" for segment in plan.timeline)
    starts = [segment.start for segment in plan.timeline]
    assert starts == sorted(starts), "时间线顺序"


def test_full_scene_cap_and_texts() -> None:
    plan = build_full("ep1", _scenes(), _STRATEGY, "透视眼", genre="逆袭")
    assert len(plan.timeline) <= 8
    assert len(plan.narration_texts) == len(plan.timeline)
    assert "透视眼" in plan.narration_texts[0].text
    assert "逆袭" in plan.narration_texts[0].text
    assert "全集" in plan.narration_texts[-1].text


def test_narration_texts_position_semantics() -> None:
    scenes = _scenes()[:4]
    texts = narration_texts_for(scenes, "剧名", None)
    assert len(texts) == 4
    assert "剧名" in texts[0].text
    assert "冲突直接拉满" in texts[1].text, "score>=85 的高潮分支优先于位置分支"
    assert "麻烦" in texts[2].text  # 偶数位埋悬念
    assert "全集" in texts[3].text  # 收尾


def test_full_empty_scenes() -> None:
    plan = build_full("ep1", [], _STRATEGY, "x")
    assert plan.timeline == []
