"""评审分趟对照实验的纯函数：对照稿、分趟提示词、解析、指标。"""

from __future__ import annotations

from typing import Any

import pytest

from dramaclip.engines.narration import variant_scoring
from tools import review_ab_core as core

_TEXTS = ("开头一", "开头二", "中段一", "中段二", "中段三", "结尾一", "结尾二")


def test_local_parts_split_the_script_into_opening_middle_and_ending() -> None:
    assert core.local_parts(_TEXTS) == (
        "开头一\n开头二",
        "中段一\n中段二\n中段三",
        "结尾一\n结尾二",
    )
    assert core.local_parts(("一", "二", "三")) == ("一", "二", "三")
    assert core.local_parts(("一", "二")) == ("一\n二", "", "一\n二")


def test_plain_keeps_the_script_untouched() -> None:
    item = core.degrade("base", _TEXTS, core.PLAIN, 1)

    assert item is not None and item.texts == _TEXTS and item.item_id == "base-plain"


def test_pad_open_delays_the_hook_with_announcer_filler() -> None:
    item = core.degrade("base", _TEXTS, core.PAD_OPEN, 1)

    assert item is not None
    assert item.texts == (*core._OPENING_PAD, *_TEXTS), "只在前头垫报幕腔：原稿一字不动，整段后移"


def test_flat_end_drops_the_call_to_action() -> None:
    item = core.degrade("base", _TEXTS, core.FLAT_END, 1)

    assert item is not None and item.texts == _TEXTS[:-1]
    short = core.degrade("base", _TEXTS[:3], core.FLAT_END, 1)
    assert short is not None and short.texts[-1] == core._FLAT_ENDING, "没有导看段可去的补一句平收"


def test_shuffle_mid_is_deterministic_and_keeps_both_ends() -> None:
    first = core.degrade("base", _TEXTS, core.SHUFFLE_MID, 7)
    again = core.degrade("base", _TEXTS, core.SHUFFLE_MID, 7)
    other = core.degrade("base", _TEXTS, core.SHUFFLE_MID, 8)

    assert first is not None and again is not None and other is not None
    assert first.texts == again.texts, "同一种子必须是同一份对照稿：重跑要能对上"
    assert first.texts[0] == _TEXTS[0] and first.texts[-1] == _TEXTS[-1]
    assert sorted(first.texts) == sorted(_TEXTS), "打乱只动顺序"


def test_build_items_makes_a_group_per_base() -> None:
    items = core.build_items({"a": _TEXTS, "b": _TEXTS[:3]}, seed=1)

    assert [item.cond for item in items[:4]] == list(core.CONDITIONS)
    assert {item.base for item in items} == {"a", "b"}
    assert [item.cond for item in items[4:]] == [core.PLAIN, core.PAD_OPEN, core.FLAT_END], (
        "b 段数不够、打乱不了中段：造不出的坏不占位"
    )


def test_pick_bases_takes_the_lowest_and_highest_scored_per_sample() -> None:
    texts = {f"s1-{i}": (f"稿{i}",) for i in range(4)} | {"s2-0": ("甲",), "s2-1": ("乙",)}
    yard = {"s1-0": 5.0, "s1-1": 7.0, "s1-2": 6.0, "s1-3": 8.0, "s2-0": 4.0, "s2-1": 9.0}

    picked = core.pick_bases(texts, yard, per_sample=2)

    assert sorted(picked) == ["s1-0", "s1-3", "s2-0", "s2-1"]


def test_anchors_come_from_the_production_prompt() -> None:
    anchors = core.anchors()

    assert set(anchors) == set(variant_scoring.DIMENSIONS), "六个维度的行为锚点都要取得到"
    assert all("9=" in text and "1=" in text for text in anchors.values())


def test_local_prompt_shows_one_dimension_and_demands_a_quote() -> None:
    system = core.local_system("hook_power", "9=第一句就是具体反差")

    assert "【hook_power】9=第一句就是具体反差" in system
    assert '"score"' in system and '"quote"' in system and "方案" not in system, (
        "单稿单判据，不带标签"
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"score": 7, "quote": "她想都别想", "fix": "把反差提到第一句"}, {"score": 7.0}),
        ({"score": 12, "quote": "她想都别想", "fix": ""}, {"score": 10.0}),
        ({"score": True, "quote": "她想都别想"}, None),
        ({"score": 7, "quote": "原文里没有这句"}, None),
        ({"score": 7}, None),
        ("不是对象", None),
    ],
)
def test_parse_local_needs_a_real_score_and_a_verbatim_quote(
    raw: Any, expected: dict[str, Any] | None
) -> None:
    parsed = core.parse_local(raw, "她连车门都没上，她想都别想。")

    assert (parsed is None) == (expected is None)
    if parsed is not None and expected is not None:
        assert {key: parsed[key] for key in expected} == expected


def test_parse_whole_requires_a_cited_quote_for_every_dimension() -> None:
    text = "她掏不出六千块，新郎转头就走。"
    good = {
        "dims": {"conflict_clarity": 8, "emotion_curve": 7},
        "quotes": {"conflict_clarity": "掏不出六千块", "emotion_curve": "新郎转头就走"},
    }
    uncited = {
        "dims": {"conflict_clarity": 8, "emotion_curve": 7},
        "quotes": {"conflict_clarity": "掏不出六千块", "emotion_curve": "编的"},
    }

    parsed = core.parse_whole(good, text)

    assert parsed is not None and parsed["dims"] == {"conflict_clarity": 8.0, "emotion_curve": 7.0}
    assert core.parse_whole(uncited, text) is None, "有一维没引到原文就整趟作废"


def test_parse_quoted_needs_all_six_dimensions() -> None:
    dims = {
        "hook_power": 8,
        "rhythm": 7,
        "emotion_curve": 7,
        "conflict_clarity": 8,
        "cta_pull": 9,
        "visual_potential": 6,
    }
    quotes = {dim: "她走了" for dim in dims}

    full = core.parse_quoted(
        {"dims": dims, "quotes": quotes, "suggestion": "开头再狠一点"}, "她走了"
    )
    partial = core.parse_quoted(
        {"dims": {k: v for k, v in dims.items() if k != "cta_pull"}, "quotes": quotes}, "她走了"
    )

    assert full is not None and full["suggestion"] == "开头再狠一点"
    assert partial is None, "少一维的总分与别的评审不同尺"


def _passes(
    hook: float, middle: float, ending: float, whole: dict[str, float]
) -> dict[str, dict[str, Any]]:
    return {
        "hook": {"score": hook, "quote": "开头", "fix": ""},
        "middle": {"score": middle, "quote": "中段", "fix": ""},
        "ending": {"score": ending, "quote": "结尾", "fix": ""},
        "whole": {"dims": whole},
    }


def test_staged_verdict_folds_each_pass_into_its_own_dimension() -> None:
    item = core.Item("b-plain", "b", core.PLAIN, _TEXTS)
    whole = {"conflict_clarity": 8.0, "emotion_curve": 7.0, "visual_potential": 6.0}

    verdict = core.staged_verdict(item, _passes(9, 6, 8, whole))

    assert verdict is not None
    flat = {"hook_power": 9.0, "rhythm": 6.0, "cta_pull": 8.0, **whole}
    assert verdict.total == variant_scoring.weighted_total(flat), "总分口径与线上同一个加权"


def test_staged_verdict_is_void_without_every_dimension() -> None:
    item = core.Item("b-plain", "b", core.PLAIN, _TEXTS)
    whole = {"conflict_clarity": 8.0, "emotion_curve": 7.0, "visual_potential": 6.0}

    passes = _passes(9, 6, 8, whole)
    del passes["ending"]

    assert core.staged_verdict(item, passes) is None


def _judge(name: str, plain: float, damaged: float) -> list[core.Verdict]:
    return [
        core.Verdict(
            name, f"b{i}-{cond}", f"b{i}", cond, plain if cond == core.PLAIN else damaged, {}
        )
        for i in range(3)
        for cond in core.CONDITIONS
    ]


def test_metrics_credit_a_judge_that_recognises_damage() -> None:
    yard = {
        f"b{i}-{cond}": (8.0 if cond == core.PLAIN else 5.0)
        for i in range(3)
        for cond in core.CONDITIONS
    }

    sharp = core.metrics(_judge("sharp", 8.0, 6.0), yard)
    blind = core.metrics(_judge("blind", 7.0, 7.0), yard)

    assert sharp.plain_top == 1.0 and sharp.detected == {
        c: 1.0 for c in core.CONDITIONS if c != core.PLAIN
    }
    assert sharp.gap == {core.PAD_OPEN: 2.0, core.FLAT_END: 2.0, core.SHUFFLE_MID: 2.0}
    assert sharp.pearson == pytest.approx(1.0) and sharp.yard_top_match == 1.0
    assert blind.plain_top == 0.0 and set(blind.gap.values()) == {0.0}


def test_metrics_ignore_groups_that_miss_a_condition() -> None:
    """四份缺一份的组算不出「原稿排第一」：不进账，也不许把它算成没认出来。"""
    verdicts = _judge("sharp", 8.0, 6.0)[:3]  # b0 只有 plain / pad_open / flat_end
    yard = {v.item_id: v.total for v in verdicts}

    sharp = core.metrics(verdicts, yard)

    assert sharp.plain_top == 0.0 and sharp.gap[core.SHUFFLE_MID] == 0.0


def test_report_renders_one_row_per_judge() -> None:
    yard = {
        f"b{i}-{cond}": (8.0 if cond == core.PLAIN else 5.0)
        for i in range(3)
        for cond in core.CONDITIONS
    }
    tables = [
        core.metrics(_judge("sharp", 8.0, 6.0), yard),
        core.metrics(_judge("blind", 7.0, 7.0), yard),
    ]

    text = core.render_report(tables, {"hook": {core.PAD_OPEN: 1.5}})

    assert "| sharp | 12 |" in text and "| blind | 12 |" in text
    assert "100%（+2.0）" in text and "开头垫铺垫 +1.5" in text
