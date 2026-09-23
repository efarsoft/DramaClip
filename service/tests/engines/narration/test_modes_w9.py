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


# ---- B9 节拍吸附 ---------------------------------------------------------
# 夹具用**空台词表**（asr=[]，与 w5 侧 B9 夹具同口径）：A3 之后有台词的场景窗长
# 会收缩到台词 span+尾垫，而本组钉的是纯吸附行为。空台词 → 不收缩 → 各段窗口 =
# [scene.start, scene.start + 8s]（场景都长 12s，所以每个 end 都是「起点+8」的
# 任意点，正是该被吸附到节拍上的那类切点；场景 start 不动——镜头边界语义点）。
# 基线（无 beats）各 end：8.0 / 18.0 / 28.0 / 38.0 / 48.0 / 58.0，CTA 59.0→62.0。
# A3 的「吸附在收缩之后」由 test_scene_window_fit.py 带台词夹具单独钉。


def _material_with_beats(beats: list[float]) -> casting.MaterialByEpisode:
    return {"ep1": casting.EpisodeMaterial(number=1, asr=[], beats=tuple(beats))}


def _material_no_beats() -> casting.MaterialByEpisode:
    """无台词、无 beats 字段（默认 ()）：吸附基线的对照面。"""
    return {"ep1": casting.EpisodeMaterial(number=1, asr=[])}


def _ends(plan: object) -> list[float]:
    from dramaclip.engines.narration.models import PlanData

    assert isinstance(plan, PlanData)
    return [segment.end for segment in plan.timeline]


def test_scene_window_ends_snap_to_beats() -> None:
    """拍点落在每个窗口 end 前 0.2s（容差内）：六个 end 全部吸附，
    场景 start 不动——它是镜头边界语义点。"""
    beats = [7.8, 17.8, 27.8, 37.8, 47.8, 57.8]
    plan = build_subtitle_flow(
        stamp([(1, "ep1", _scenes())]), _material_with_beats(beats), _STRATEGY
    )
    body = plan.timeline[:-1]
    assert [segment.start for segment in body] == [0.0, 10.0, 20.0, 30.0, 40.0, 50.0]
    assert [segment.end for segment in body] == beats


def test_beat_beyond_tolerance_leaves_end_alone() -> None:
    """拍栅格偏开 0.4s（>0.25 容差）：每个 end 都够不着拍，计划与不吸附逐点一致。
    宁可不卡点也不把切点挪出容差。"""
    beats = [round(0.4 + n * 1.0, 3) for n in range(0, 200)]
    plan = build_subtitle_flow(
        stamp([(1, "ep1", _scenes())]), _material_with_beats(beats), _STRATEGY
    )
    assert _ends(plan) == [8.0, 18.0, 28.0, 38.0, 48.0, 58.0, 62.0]


def test_cta_card_is_never_snapped() -> None:
    """CTA 卡收尾引导有自己的节奏（3s 定长卡），不参与节拍吸附：
    唯一的拍点在 62.1s（CTA end=62.0 的容差内），CTA 仍是 62.0。"""
    plan = build_subtitle_flow(
        stamp([(1, "ep1", _scenes())]), _material_with_beats([62.1]), _STRATEGY
    )
    cta = plan.timeline[-1]
    assert (cta.start, cta.end) == (59.0, 62.0)


def test_empty_beats_plan_is_byte_identical_to_the_unsnapped_baseline() -> None:
    """旧库降级（beats=[]）：计划必须与现状逐字节一致——这是 B9 的硬验收标准，
    钉成可执行断言而不是口头承诺。"""
    baseline = build_subtitle_flow(
        stamp([(1, "ep1", _scenes())]), _material_no_beats(), _STRATEGY
    )
    degraded = build_subtitle_flow(
        stamp([(1, "ep1", _scenes())]), _material_with_beats([]), _STRATEGY
    )
    assert degraded.model_dump_json() == baseline.model_dump_json()
    assert _ends(degraded) == [8.0, 18.0, 28.0, 38.0, 48.0, 58.0, 62.0]


def test_default_beats_is_empty_tuple_for_existing_construction_sites() -> None:
    """EpisodeMaterial.beats 默认 ()：既有构造点（不传 beats）全兼容。"""
    material = casting.EpisodeMaterial(number=1, asr=[])
    assert tuple(material.beats) == ()
