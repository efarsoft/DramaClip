"""取材层：集身份注入、跨集叙事排序、按集取台词。

夹具全手搓，不跑分析层：本模块是纯函数，把上游拉进来只会让"身份盖错了"与
"冲突分算错了"两种失败混在一起。

这里钉的四件事各对应一个真实的坏法：
① 盖章（`stamp`）——身份丢了，段的 episode_id 就只能是调用方随手给的那一集；
② 叙事排序（`episode_order`）——活库实测十集的场景起点全部从 0.0 开始，
   跨集仍按 start 排会把十集交错成一条谁也不是的时间线；
③ 分数排序的确定性（`score_order`）——活库 333 个场景只有 19 个不同分值，
   同分不补次键就稳定于输入顺序，而输入顺序没有契约；
④ 按集取台词（`dialogue_of`）——摊平一张表按秒过滤会把别的集的对白喂给编剧，
   而编剧被 §3.3.1 要求"只能来自给定台词"，于是它照着错的台词写出一段通顺的假解说。
"""

from __future__ import annotations

import pytest

from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.narration import casting
from dramaclip.engines.semantic.models import ConflictScore


def _scene(index: int, start: float, score: int) -> ConflictScore:
    return ConflictScore(
        scene_index=index, start=start, end=start + 6.0, score=score, reason="冲突"
    )


def _line(start: float, text: str) -> AsrSegment:
    return AsrSegment(start=start, end=start + 2.0, text=text)


def test_stamp_attaches_the_episode_identity_of_the_row_it_came_from() -> None:
    stamped = casting.stamp(
        [
            (3, "ep-three", [_scene(0, 0.0, 90)]),
            (7, "ep-seven", [_scene(0, 0.0, 80), _scene(1, 12.0, 70)]),
        ]
    )
    assert [(item.number, item.episode_id) for item in stamped] == [
        (3, "ep-three"),
        (7, "ep-seven"),
        (7, "ep-seven"),
    ]
    # 原有五个字段一个都不能丢（reason 尤其容易在"逐字段抄"的写法里被漏掉）
    assert [(item.scene_index, item.start, item.score, item.reason) for item in stamped] == [
        (0, 0.0, 90, "冲突"),
        (0, 0.0, 80, "冲突"),
        (1, 12.0, 70, "冲突"),
    ]


def test_stamp_survives_a_new_field_on_conflictscore() -> None:
    """盖章走 model_dump/model_validate，不走逐字段抄。

    逐字段抄在 `ConflictScore` 加字段那天会**静默丢掉**新字段：pydantic 默认忽略未知
    kwargs，照抄旧字段名不报错，只会少一个值（P-1.5《实现定案修正》正是为这件事写的）。
    这条用例把"不丢字段"钉成可执行的断言，而不是注释里的一句提醒。
    """
    payload = _scene(0, 0.0, 90).model_dump()
    assert set(casting.stamp([(1, "ep1", [_scene(0, 0.0, 90)])])[0].model_dump()) >= set(payload)


def test_episode_order_is_broadcast_order_not_clock_order() -> None:
    """两集的 0.0s 是两段不同画面：先按集号、再按集内起点。"""
    late = casting.stamp([(7, "ep7", [_scene(0, 0.0, 90)])])[0]
    early = casting.stamp([(3, "ep3", [_scene(0, 0.0, 40)])])[0]
    ordered = sorted([late, early], key=casting.episode_order)
    assert [item.number for item in ordered] == [3, 7], "按 start 排会把两集的 0.0s 混在一起"


def test_episode_order_breaks_ties_by_scene_index() -> None:
    """同集同起点（零长场景与舍入会让 start 相等）时补 scene_index，才有可复现的顺序。"""
    a = casting.stamp([(1, "ep1", [_scene(5, 0.0, 90)])])[0]
    b = casting.stamp([(1, "ep1", [_scene(2, 0.0, 40)])])[0]
    assert casting.episode_order(b) < casting.episode_order(a)


def test_score_order_is_deterministic_across_input_order() -> None:
    """同分不补次键就稳定于输入顺序，而输入顺序来自 list_by_project，没有契约。"""
    first = casting.stamp([(2, "ep2", [_scene(1, 5.0, 85)]), (1, "ep1", [_scene(9, 5.0, 85)])])
    second = casting.stamp([(1, "ep1", [_scene(9, 5.0, 85)]), (2, "ep2", [_scene(1, 5.0, 85)])])
    assert [min(first, key=casting.score_order).number] == [1]
    assert [min(second, key=casting.score_order).number] == [1]


def test_score_order_puts_the_highest_score_first() -> None:
    scenes = casting.stamp([(1, "ep1", [_scene(0, 0.0, 60), _scene(1, 10.0, 95)])])
    assert min(scenes, key=casting.score_order).score == 95


def test_dialogue_of_returns_only_that_episodes_lines() -> None:
    material = {
        "ep3": casting.EpisodeMaterial(number=3, asr=[_line(12.0, "第三集的话")]),
        "ep7": casting.EpisodeMaterial(number=7, asr=[_line(12.0, "第七集的话")]),
    }
    assert [seg.text for seg in casting.dialogue_of(material, "ep3")] == ["第三集的话"]


def test_dialogue_of_raises_on_a_missing_episode_instead_of_looking_silent() -> None:
    """缺键 ≠ 这一集没有台词：静默返回空表会让编剧写出一段什么都不说的解说。"""
    material = {"ep3": casting.EpisodeMaterial(number=3, asr=[_line(12.0, "第三集的话")])}
    with pytest.raises(ValueError, match="没有装配进来"):
        casting.dialogue_of(material, "ep7")


def test_label_of_names_the_episode_for_the_copy_prompt() -> None:
    material = {"ep3": casting.EpisodeMaterial(number=3, asr=[])}
    assert casting.label_of(material, "ep3") == "第3集"
    with pytest.raises(ValueError, match="无从给出集名"):
        casting.label_of(material, "ep7")
