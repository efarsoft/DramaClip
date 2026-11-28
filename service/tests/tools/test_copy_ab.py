"""文案规则 A/B 工具：纯函数半边（试验变量 / 配对换位 / 判决聚合 / 判定线）与命令行参数。

不联网、不碰库。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Any

import pytest

from dramaclip.engines.narration import scriptwriter
from dramaclip.engines.narration.prompt_rules import RULE_TEXTS
from tools import copy_ab as cli
from tools import copy_ab_core as ab
from tools import copy_ab_score as scoring


def _script(
    sample_id: str, variant: str, index: int, texts: tuple[str, ...], *, ok: bool = True
) -> ab.Script:
    return ab.Script(f"{sample_id}-{variant}{index}", sample_id, variant, index, ok, texts, 0, "")


def _sample(sample_id: str) -> ab.Sample:
    return ab.Sample(sample_id, "剧名", "复仇", ("e1",), (1,), "角度", "切入角度：…", (1,))


# ── 试验变量 ──
def test_variant_b_swaps_exactly_two_sentences() -> None:
    base = scriptwriter.FUNDAMENTALS
    old_rule = RULE_TEXTS[ab.OLD_RULE_KEY]
    assert base.count(old_rule) == 1 and base.count(ab.OLD_EXAMPLE) == 1

    variant_b = ab.variant_b_fundamentals()

    assert ab.NEW_RULE in variant_b and ab.NEW_EXAMPLE in variant_b
    assert old_rule not in variant_b and ab.OLD_EXAMPLE not in variant_b
    # 换回去与 A 版逐字相同：除这两句，B 没动别的地方
    restored = variant_b.replace(ab.NEW_RULE, old_rule).replace(ab.NEW_EXAMPLE, ab.OLD_EXAMPLE)
    assert restored == base


def test_variant_settings_only_adds_override_for_b() -> None:
    base = {"llm.model": "m", "narration.flow_style": "1"}
    sample = _sample("s1")

    settings_a = ab.variant_settings(base, sample, ab.VARIANT_A)
    settings_b = ab.variant_settings(base, sample, ab.VARIANT_B)

    assert ab.FUNDAMENTALS_KEY not in settings_a
    assert settings_b[ab.FUNDAMENTALS_KEY] == ab.variant_b_fundamentals()
    for settings in (settings_a, settings_b):
        assert settings["_project_name"] == "剧名"
        assert settings["_genre"] == "复仇"
        assert settings["_style_directives"] == ""
        assert settings["narration.flow_style"] == "0"
    assert base["narration.flow_style"] == "1"  # 入参不被改动


# ── 配对与呈现 ──
def test_build_pairs_counts_and_skips_failed_scripts() -> None:
    scripts = [
        _script("s1", "A", 1, ("甲",)),
        _script("s1", "A", 2, ("乙",)),
        _script("s1", "B", 1, ("丙",)),
        _script("s1", "B", 2, ("丁",)),
        _script("s1", "B", 3, (), ok=False),
        _script("s2", "A", 1, ("戊",)),
    ]
    pairs = ab.build_pairs(scripts)

    kinds = [pair.kind for pair in pairs]
    assert kinds.count("ab") == 4 and kinds.count("aa") == 1 and kinds.count("bb") == 1
    assert {pair.sample_id for pair in pairs} == {"s1"}  # s2 没有成稿的 B，组不成对
    assert all("s1-B3" not in (pair.left_id, pair.right_id) for pair in pairs)


def test_build_presents_swaps_and_is_reproducible() -> None:
    scripts = [
        _script("s1", "A", 1, ("甲",)),
        _script("s1", "A", 2, ("乙",)),
        _script("s1", "B", 1, ("丙",)),
    ]
    pairs = ab.build_pairs(scripts)

    presents = ab.build_presents(pairs, seed=7)

    assert len(presents) == 2 * len(pairs)
    for pair in pairs:
        mine = [present for present in presents if present.pair_id == pair.pair_id]
        assert [present.order_no for present in mine] == [1, 2]
        assert (mine[0].first_id, mine[0].second_id) == (mine[1].second_id, mine[1].first_id)
    assert presents == ab.build_presents(pairs, seed=7)


# ── 判决 ──
def test_parse_judgment_accepts_only_contract_shape() -> None:
    good = {"prefer": "乙", "quote_甲": "a", "quote_乙": "b", "reason": "r"}
    assert ab.parse_judgment(good) == ("乙", "a", "b", "r")
    assert ab.parse_judgment({"prefer": "都不好"}) is None
    assert ab.parse_judgment(["甲"]) is None


def test_quote_found_ignores_whitespace_and_wrapping_quotes() -> None:
    text = "她攥紧了指节，\n眼眶红了。"
    assert ab.quote_found("「攥紧了指节，眼眶红了」", text)
    assert not ab.quote_found("", text)
    assert not ab.quote_found("她笑了", text)


def _judgment(present: ab.Present, picked: str) -> ab.Judgment:
    return ab.Judgment(
        present.pair_id, present.order_no, present.first_id, picked, True, "理由", "q", "q", ""
    )


def test_verdicts_need_both_orders_to_agree() -> None:
    pair = ab.Pair("p", "ab", "s1", "s1-A1", "s1-B1")
    first = ab.Present("p", "ab", "s1", 1, "s1-A1", "s1-B1")
    second = ab.Present("p", "ab", "s1", 2, "s1-B1", "s1-A1")

    assert (
        ab.verdicts([pair], [_judgment(first, "s1-B1"), _judgment(second, "s1-B1")])["p"] == "s1-B1"
    )
    assert (
        ab.verdicts([pair], [_judgment(first, "s1-B1"), _judgment(second, "s1-A1")])["p"] == "tie"
    )
    assert ab.verdicts([pair], [_judgment(first, ""), _judgment(second, "")])["p"] == "tie"
    assert ab.verdicts([pair], [_judgment(first, "s1-B1")])["p"] == "invalid"


# ── 判定线 ──
_BODY_A = ("她攥紧了指节。", "她攥紧了指节。", "她攥紧了指节。", "她攥紧了指节。", "他怕了。")
_BODY_B = ("她慌了。", "他气坏了。", "她怕了。", "他愣了。")


def _script_set(plain_in_b: bool = True) -> list[ab.Script]:
    body_b = _BODY_B if plain_in_b else ("她攥紧了指节。",) * 4
    return [
        _script(sample, variant, index, _BODY_A if variant == "A" else body_b)
        for sample in ("s1", "s2")
        for variant in ("A", "B")
        for index in (1, 2)
    ]


def _winner(pair: ab.Pair) -> str:
    """跨版对照的胜方：s1 上 B 胜 3 / A 胜 1，s2 上 2 / 2——合计 B 5 / A 3。"""
    a_wins = {"s1:ab:s1-A1:s1-B1", "s2:ab:s2-A1:s2-B1", "s2:ab:s2-A1:s2-B2"}
    if pair.kind == "ab" and pair.pair_id in a_wins:
        return pair.left_id
    return pair.left_id if pair.kind == "aa" else pair.right_id


def _judged(
    pairs: list[ab.Pair], winner_of: Callable[[ab.Pair], str] = _winner
) -> list[ab.Judgment]:
    by_id = {pair.pair_id: pair for pair in pairs}
    return [
        _judgment(present, winner_of(by_id[present.pair_id]))
        for present in ab.build_presents(pairs, seed=1)
    ]


def _retells(scripts: list[ab.Script]) -> dict[str, dict[str, Any]]:
    return {script.script_id: {"passed": True, "error": ""} for script in scripts}


def test_evaluate_adopts_b_when_every_line_passes() -> None:
    scripts = _script_set()
    pairs = ab.build_pairs(scripts)

    report = ab.evaluate(scripts, pairs, _judged(pairs), _retells(scripts))

    assert [check.passed for check in report.checks] == [True, True, True, True]
    assert report.adopt
    assert report.tallies["ab"].wins_b == 5 and report.tallies["ab"].wins_a == 3
    assert report.balance["all"] == 0.5  # 换位后两次选同一篇，选甲选乙各占一半


def test_evaluate_keeps_a_when_b_does_not_actually_change_emotion_wording() -> None:
    scripts = _script_set(plain_in_b=False)
    pairs = ab.build_pairs(scripts)

    report = ab.evaluate(scripts, pairs, _judged(pairs), _retells(scripts))

    assert report.checks[0].passed is False
    assert not report.adopt


def test_evaluate_keeps_a_when_judge_prefers_a() -> None:
    scripts = _script_set()
    pairs = ab.build_pairs(scripts)

    report = ab.evaluate(
        scripts, pairs, _judged(pairs, lambda pair: pair.left_id), _retells(scripts)
    )

    assert report.checks[1].passed is False
    assert not report.adopt


def test_regression_is_unknown_not_passed_when_retell_missing() -> None:
    scripts = _script_set()
    pairs = ab.build_pairs(scripts)

    report = ab.evaluate(scripts, pairs, _judged(pairs), {})

    assert report.checks[2].passed is None  # 算不出≠通过：缺数据不判绿
    assert not report.adopt


def test_position_check_band() -> None:
    assert ab._check_position(0.5).passed is True
    assert ab._check_position(0.8).passed is False
    assert ab._check_position(None).passed is False


def test_render_report_states_conclusion_and_each_line() -> None:
    scripts = _script_set()
    pairs = ab.build_pairs(scripts)
    report = ab.evaluate(scripts, pairs, _judged(pairs), _retells(scripts))

    text = ab.render_report(report, {"run_id": "r1", "writer": "w", "judge": "j", "samples": 2})

    assert "**结论：采用 B**" in text
    for check in report.checks:
        assert check.name in text
    assert "| s1 | 4 | 3 | 1 | 0 | 0 |" in text


# ── 命令行参数 ──
def test_window_and_span_parsing() -> None:
    assert cli._parse_window("dujia_open=钟情错付再回首:1-3") == (
        "dujia_open",
        "钟情错付再回首",
        "1-3",
    )
    assert cli._parse_span("7-10") == (7, 8, 9, 10)
    assert cli._parse_span("4") == (4,)
    with pytest.raises(SystemExit):
        cli._parse_window("没有等号")
    with pytest.raises(SystemExit):
        cli._parse_span("三到五")


def test_parser_wires_subcommands() -> None:
    args = cli.build_parser().parse_args(["judge", "--run", "r", "--judge", "裁判端点"])

    assert args.judge == "裁判端点"
    assert args.kinds == "ab,aa,bb" and args.tag == "" and args.judge_model == ""
    assert args.seed == 20261125 and args.workers == 4


def test_parser_wires_score_commands() -> None:
    args = cli.build_parser().parse_args(
        ["score", "--run", "r", "--judge", "Qwen", "--judge-model", "qwen4-max", "--tag", "q4"]
    )

    assert args.judge_model == "qwen4-max" and args.tag == "q4"
    assert args.repeats == 2 and args.workers == 4


# ── 独立打分协议与裁判校准统计 ──
def test_parse_score_accepts_only_integer_1_to_10() -> None:
    assert scoring.parse_score({"score": 7, "quote": "q", "reason": "r"}) == (7, "q", "r")
    for bad in ({"score": 0}, {"score": 11}, {"score": "8"}, {"score": 7.5}):
        assert scoring.parse_score(bad) is None
    assert scoring.parse_score({"score": True}) is None  # bool 是 int 子类，必须拒
    assert scoring.parse_score([7]) is None


def test_ranks_average_ties_and_correlations() -> None:
    assert scoring.ranks([10.0, 20.0, 20.0, 5.0]) == [2.0, 3.5, 3.5, 1.0]
    assert scoring.spearman([1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0]) == 1.0
    assert scoring.spearman([1.0, 2.0, 3.0, 4.0], [4.0, 3.0, 2.0, 1.0]) == -1.0
    assert scoring.pearson([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None  # 一侧全相等=算不出
    assert scoring.pearson([1.0, 2.0], [1.0, 2.0]) is None  # 不足三对=算不出


def _scored(
    scripts: list[ab.Script], judge: str, score_of: Callable[[ab.Script], int], repeats: int = 2
) -> list[dict[str, Any]]:
    return [
        asdict(
            scoring.ScoreRow(
                script.script_id,
                script.sample_id,
                script.variant,
                judge,
                repeat,
                score_of(script),
                True,
                "q",
                "r",
                "",
            )
        )
        for script in scripts
        for repeat in range(1, repeats + 1)
    ]


def test_judge_stats_perfectly_stable_judge() -> None:
    scripts = [
        _script(f"s{sample}", variant, index, (f"她慌了。{index}",))
        for sample in (1, 2, 3)
        for variant in ("A", "B")
        for index in (1, 2, 3)
    ]
    # 分数只由稿子决定：同一篇两次完全一致；B 版每篇恰比同号 A 版高一分
    rows = _scored(scripts, "裁判", lambda script: script.index + (script.variant == "B"))

    stat = scoring.judge_stats(rows, "裁判", scripts)

    assert stat is not None
    assert stat.scripts == 18 and stat.retest_r == 1.0 and stat.reliability == 1.0
    assert (stat.mean_a, stat.mean_b) == (2.0, 3.0)
    assert (stat.samples_b_ahead, stat.samples) == (3, 3)
    assert stat.density_rho is None  # 各篇密度全相等：相关算不出，不是 0


def test_judge_stats_tracks_density_and_agreement_between_judges() -> None:
    # 字数随序号变长而直白情绪词只有一个：密度随序号下降；分数也随序号下降 → 正相关
    scripts = [
        _script(f"s{sample}", "A", index, ("她慌了。" + "他走出家门。" * index,))
        for sample in (1, 2)
        for index in (1, 2, 3, 4)
    ]
    steady = _scored(scripts, "稳", lambda script: 5 - script.index)
    noisy = _scored(scripts, "噪", lambda script: script.index)

    stat = scoring.judge_stats(steady, "稳", scripts)

    assert stat is not None
    assert stat.density_rho == 1.0 and stat.density_rho_within == 1.0
    assert scoring.judges_agreement(steady, "稳", "稳") == 1.0
    assert scoring.judges_agreement(steady + noisy, "稳", "噪") == -1.0
    assert scoring.judges_agreement(noisy, "噪", "别的裁判") is None


def test_position_stats_counts_sides_and_swap_consistency() -> None:
    rows = [
        {"pair_id": "p1", "order_no": 1, "first_id": "X", "picked_id": "X", "error": ""},
        {"pair_id": "p1", "order_no": 2, "first_id": "Y", "picked_id": "Y", "error": ""},
        {"pair_id": "p2", "order_no": 1, "first_id": "X", "picked_id": "Y", "error": ""},
        {"pair_id": "p2", "order_no": 2, "first_id": "Y", "picked_id": "Y", "error": ""},
        {"pair_id": "p3", "order_no": 1, "first_id": "X", "picked_id": "", "error": ""},
        {"pair_id": "p3", "order_no": 2, "first_id": "Y", "picked_id": "X", "error": "调用失败"},
    ]

    stats = scoring.position_stats(rows)

    # p1 两次都选甲位=换位后翻盘，不一致；p2 两次都选 Y=一致；p3 一次差不多、一次无效
    assert (stats["valid"], stats["first"], stats["second"], stats["even"]) == (5, 3, 1, 1)
    assert (stats["pairs"], stats["consistent"]) == (3, 1)


def test_pending_scores_skips_what_is_already_scored() -> None:
    scripts = [_script("s1", "A", 1, ("甲",)), _script("s1", "A", 2, ("乙",))]

    pending = scoring.pending_scores(scripts, 2, {("s1-A1", 1), ("s1-A2", 2)})

    assert pending == [(scripts[0], 2), (scripts[1], 1)]


def test_score_report_names_judges_and_thresholds() -> None:
    scripts = [_script("s1", "A", 1, ("甲",))]
    rows = _scored(scripts, "裁判甲", lambda script: 5)
    stat = scoring.judge_stats(rows, "裁判甲", scripts)
    assert stat is not None
    judged = [{"pair_id": "p", "first_id": "X", "picked_id": "X", "error": ""}]

    text = scoring.render_score_report(
        [stat], {("裁判甲", "裁判甲"): 1.0}, {"裁判甲": scoring.position_stats(judged)}
    )

    assert "裁判校准（独立打分）" in text
    assert "裁判甲" in text and str(scoring.RETEST_R_MIN) in text
    assert "选先呈现 1 / 选后呈现 0" in text
