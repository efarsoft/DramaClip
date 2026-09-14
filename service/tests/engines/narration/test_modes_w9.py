"""engines.narration.modes_w9：字幕金句流编排。"""

from __future__ import annotations

from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.narration import casting
from dramaclip.engines.narration.casting import stamp
from dramaclip.engines.narration.models import StrategySpec
from dramaclip.engines.narration.modes_w9 import build_subtitle_flow
from dramaclip.engines.semantic.models import ConflictScore

_STRATEGY = StrategySpec(min_duration_s=10, max_duration_s=90)


def _scenes() -> list[ConflictScore]:
    return [
        ConflictScore(scene_index=index, start=index * 10.0, end=index * 10.0 + 12.0, score=score)
        for index, score in enumerate([70, 88, 50, 92, 60, 80, 45])
    ]


def _segments() -> list[AsrSegment]:
    return [
        AsrSegment(start=2.0, end=5.0, text="你给我滚出去！骗子！"),
        AsrSegment(start=12.0, end=15.0, text="普通的一句"),
        AsrSegment(start=32.0, end=36.0, text="我要报仇！都给我等着！"),
        AsrSegment(start=52.0, end=55.0, text="没想到这一切都是局"),
        AsrSegment(start=62.0, end=64.0, text="哈"),
        AsrSegment(start=72.0, end=75.0, text="真相就是如此"),
    ]


def _material() -> casting.MaterialByEpisode:
    return {"ep1": casting.EpisodeMaterial(number=1, asr=_segments())}


def test_picks_strongest_line_per_scene() -> None:
    plan = build_subtitle_flow(stamp([(1, "ep1", _scenes())]), _material(), _STRATEGY)
    assert plan.mode == "subtitle_flow"
    scenes_texts = [
        segment.subtitle_text
        for segment in plan.timeline[:-1]  # 排除 CTA
    ]
    assert "你给我滚出去！骗子！" in scenes_texts, "金句应被选中"
    # idx6 场景(score=45)被排除，其内对白"真相就是如此"不应出现
    assert "真相就是如此" not in scenes_texts
    assert "没想到这一切都是局" in scenes_texts, "idx5 场景唯一对白作为字幕"


def test_cta_card_appended() -> None:
    plan = build_subtitle_flow(stamp([(1, "ep1", _scenes())]), _material(), _STRATEGY)
    cta = plan.timeline[-1]
    assert cta.subtitle_text is not None and "全集" in cta.subtitle_text
    assert cta.start == 59.0 and cta.end == 62.0, "CTA 复用最后场景尾部"


def test_scene_cap_and_original_audio() -> None:
    plan = build_subtitle_flow(stamp([(1, "ep1", _scenes())]), _material(), _STRATEGY)
    body = plan.timeline[:-1]
    assert len(body) <= 6
    assert all(segment.audio == "original" for segment in plan.timeline)


def test_empty_scenes_safe() -> None:
    plan = build_subtitle_flow([], _material(), _STRATEGY)
    assert plan.timeline == []
