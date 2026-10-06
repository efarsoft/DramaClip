"""engines.narration.modes_w5：交叉解说与超短悬念版编排。"""

from __future__ import annotations

from dramaclip.engines.narration import casting, pipeline
from dramaclip.engines.narration.casting import stamp
from dramaclip.engines.narration.models import StrategySpec
from dramaclip.engines.narration.modes_w5 import build_cross, build_ultra_short
from dramaclip.engines.semantic.models import ConflictScore
from tests.engines.narration.conftest import assert_slots_paired

_STRATEGY = StrategySpec()


def _scenes() -> list[ConflictScore]:
    return [
        ConflictScore(scene_index=index, start=index * 20.0, end=index * 20.0 + 15.0, score=score)
        for index, score in enumerate([60, 85, 45, 90, 55, 75, 40, 95])
    ]


def test_cross_alternates_original_and_narration() -> None:
    plan = build_cross(stamp([(1, "ep1", _scenes())]), _STRATEGY)
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


def test_cross_keeps_top_scenes_without_duration_chop() -> None:
    strategy = StrategySpec()
    plan = build_cross(stamp([(1, "ep1", _scenes())]), strategy)
    originals = [seg for seg in plan.timeline if seg.audio == "original"]
    assert len(originals) == 6, "交叉解说取冲突 top 6，不再按时长预算提前停"


def test_ultra_short_structure() -> None:
    plan = build_ultra_short(stamp([(1, "ep1", _scenes())]), _STRATEGY)
    assert plan.mode == "ultra_short_hook"
    assert [segment.audio for segment in plan.timeline] == ["narration", "original", "narration"]
    assert [t.id for t in plan.narration_texts] == ["hook-1", "cta-1"]
    assert_slots_paired(plan, "ultra_short_hook")
    # 三拍互不重叠、素材全保留（2026-10-06 裁决「保障素材时长，不裁」）：
    # 冲突分最高的场景（score=95, [140,155]）原声拍原地不动；钩子压在它之前的
    # 素材上、尾锚在场景开头；CTA 排在原声拍之后按公式句预算留画面。
    hook, conflict, cta = plan.timeline
    assert (hook.start, hook.end) == (110.0, 140.0)
    assert (conflict.start, conflict.end) == (140.0, 148.0)  # 无台词 span → 8s 冲突窗
    assert (cta.start, cta.end) == (148.0, 163.0)


def test_ultra_short_empty_scenes() -> None:
    plan = build_ultra_short([], _STRATEGY)
    assert plan.timeline == []


# ---- B9 节拍吸附 ---------------------------------------------------------
# 交叉解说夹具的场景起点 [0, 20, 60, 80, 100, 140]（top6 按叙事顺序）：
# 原声段 end = start+8（任意点，应吸附），旁白段 end = anchor.start+4
# （由 TTS 实测回填的估计位，不吸附）。超短版冲突窗口 end = 140+8 = 148。
_BEATS_NEAR_ORIGINAL_ENDS = [7.9, 27.9, 67.9, 87.9, 107.9, 147.9]


def _material_with_beats(beats: tuple[float, ...]) -> casting.MaterialByEpisode:
    return {"ep1": casting.EpisodeMaterial(number=1, asr=[], beats=beats)}


def test_cross_original_ends_snap_but_narration_ends_do_not() -> None:
    """原声段 end 吸附到 0.1s 外的拍点；23.9 这个拍点紧贴第一个旁白段 end（24.0），
    旁白段仍不动——旁白段长由 TTS 实测回填（批次一逻辑），规划期吸附它没有意义。"""
    beats = tuple(_BEATS_NEAR_ORIGINAL_ENDS) + (23.9,)
    plan = build_cross(stamp([(1, "ep1", _scenes())]), _STRATEGY, _material_with_beats(beats))
    originals = [seg for seg in plan.timeline if seg.audio == "original"]
    narrations = [seg for seg in plan.timeline if seg.audio == "narration"]
    assert [seg.end for seg in originals] == _BEATS_NEAR_ORIGINAL_ENDS
    # 起点是镜头边界，不吸附
    assert [seg.start for seg in originals] == [0.0, 20.0, 60.0, 80.0, 100.0, 140.0]
    assert [seg.end for seg in narrations] == [24.0, 64.0, 84.0, 104.0, 144.0, 144.0]


def test_ultra_short_conflict_window_snaps_hook_and_cta_do_not() -> None:
    """冲突窗口 end 155 → 147.9（吸附 147.9 拍点）；钩子 end（140.0）与 CTA 两端
    都不吸附——旁白段的长度归 TTS 实测回填，不归节拍。"""
    beats = (143.9, 147.9, 154.9)
    plan = build_ultra_short(stamp([(1, "ep1", _scenes())]), _STRATEGY, _material_with_beats(beats))
    hook, conflict, cta = plan.timeline
    assert (hook.start, hook.end) == (110.0, 140.0)
    assert (conflict.start, conflict.end) == (140.0, 147.9)
    assert (cta.start, cta.end) == (147.9, 162.9)


def test_ultra_short_picks_a_scene_that_fits_hook_and_cta_budgets() -> None:
    """可行性选景（2026-10-06 裁决「保障素材时长」）：最高分场景贴着集尾、CTA
    预算放不下时，按分值序取第一个「前面放得下钩子、集尾放得下 CTA」的场景；
    修法之前这种形状会在回填时整条判死（真机：61 字钩子把 CTA 顶出集尾）。"""
    scenes = [
        ConflictScore(scene_index=0, start=60.0, end=74.0, score=95),  # 集尾只剩 3s，CTA 放不下
        ConflictScore(scene_index=1, start=30.0, end=44.0, score=60),  # 前 30 ✓ 集尾 33 ✓
    ]
    plan = build_ultra_short(stamp([(1, "ep1", scenes)]), _STRATEGY, None, {"ep1": 77.0})
    hook, conflict, cta = plan.timeline
    assert (conflict.start, conflict.end) == (30.0, 38.0)  # 无台词 span → 8s 冲突窗
    assert (hook.start, hook.end) == (0.0, 30.0)
    assert (cta.start, cta.end) == (38.0, 53.0)


def test_ultra_short_stores_score_ordered_scene_pool() -> None:
    """候选池 = 分值序前 6 个场景的冲突窗（含已选那个）：出片时布局按实测时长挑。"""
    plan = build_ultra_short(stamp([(1, "ep1", _scenes())]), _STRATEGY)
    assert len(plan.scene_pool) == 6, "池深度 = _ULTRA_POOL_SIZE，不足时取全部"
    assert (plan.scene_pool[0].start, plan.scene_pool[0].end) == (140.0, 148.0)
    assert plan.scene_pool[0].episode_id == "ep1"


def test_ultra_short_without_durations_keeps_highest_score_scene() -> None:
    """没传集时长（旧调用形状）不做可行性筛选：仍然取最高分场景，只换布局。"""
    scenes = [
        ConflictScore(scene_index=0, start=60.0, end=74.0, score=95),
        ConflictScore(scene_index=1, start=30.0, end=44.0, score=60),
    ]
    plan = build_ultra_short(stamp([(1, "ep1", scenes)]), _STRATEGY)
    conflict = plan.timeline[1]
    assert (conflict.start, conflict.end) == (60.0, 68.0)


def test_cross_without_material_is_byte_identical() -> None:
    """不传 material（现有 pipeline/测试的调用形状）：计划与现状逐字节一致。
    material 缺该集键、beats 空同样降级——B9 的硬验收标准。"""
    baseline = build_cross(stamp([(1, "ep1", _scenes())]), _STRATEGY)
    assert build_cross(stamp([(1, "ep1", _scenes())]), _STRATEGY, None).model_dump_json() == (
        baseline.model_dump_json()
    )
    assert build_cross(
        stamp([(1, "ep1", _scenes())]), _STRATEGY, _material_with_beats(())
    ).model_dump_json() == baseline.model_dump_json()
    other_ep = _material_with_beats(tuple(_BEATS_NEAR_ORIGINAL_ENDS))
    other_ep.pop("ep1")
    assert build_cross(
        stamp([(1, "ep1", _scenes())]), _STRATEGY, other_ep
    ).model_dump_json() == baseline.model_dump_json()


def test_ultra_short_without_material_is_byte_identical() -> None:
    baseline = build_ultra_short(stamp([(1, "ep1", _scenes())]), _STRATEGY)
    assert build_ultra_short(
        stamp([(1, "ep1", _scenes())]), _STRATEGY, None
    ).model_dump_json() == baseline.model_dump_json()
    assert build_ultra_short(
        stamp([(1, "ep1", _scenes())]), _STRATEGY, _material_with_beats(())
    ).model_dump_json() == baseline.model_dump_json()


# ---- B9 贯通：build_plan 真把 material 传进 w5 两模式（生产链路接线） ----
# 子任务因 pipeline.py 在禁碰清单，build_cross/build_ultra_short 的 material 参数
# 默认 None，生产端吸附未激活；parent 接线后这两条钉住「material 经 build_plan
# 流到 w5、吸附真发生」，防止接线被回退成静默不吸附。


def test_build_plan_threads_material_into_cross_narration() -> None:
    """经 build_plan 的 cross_narration：带拍点的 material 真流到 build_cross 并吸附。

    不传 material 时原声段 end 是任意点 start+8；传了紧贴的拍点后吸附过去——
    证明 pipeline 把 material 透传给了 w5（否则两版会逐字节相同）。
    """
    beats = tuple(_BEATS_NEAR_ORIGINAL_ENDS)
    snapped = pipeline.build_plan(
        "cross_narration",
        stamp([(1, "ep1", _scenes())]),
        [],
        _material_with_beats(beats),
        {},
    )
    unsnapped = pipeline.build_plan(
        "cross_narration", stamp([(1, "ep1", _scenes())]), [], {}, {}
    )
    originals = [seg for seg in snapped.timeline if seg.audio == "original"]
    assert [seg.end for seg in originals] == _BEATS_NEAR_ORIGINAL_ENDS, "拍点已吸附"
    assert snapped.model_dump_json() != unsnapped.model_dump_json(), "material 确实改变了产出"


def test_build_plan_threads_material_into_ultra_short() -> None:
    """经 build_plan 的 ultra_short_hook：冲突窗口 end 吸附，hook/CTA 段不动。"""
    snapped = pipeline.build_plan(
        "ultra_short_hook",
        stamp([(1, "ep1", _scenes())]),
        [],
        _material_with_beats((143.9, 147.9, 154.9)),
        {},
    )
    hook, conflict, cta = snapped.timeline
    assert (hook.start, hook.end) == (110.0, 140.0), "hook 尾锚在冲突场景开头，不吸附"
    assert (conflict.start, conflict.end) == (140.0, 147.9), "冲突窗口 end 吸附到拍点"
    assert (cta.start, cta.end) == (147.9, 162.9), "CTA 段不吸附"
