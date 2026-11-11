"""B3-13 质量黄金集量化回归：指标算法 + 漂移门禁 + 诚实纪律（算不出=未知不判绿）。"""

from __future__ import annotations

from pathlib import Path

from tools import quality_eval as qe


def _drift_args(**overrides: object) -> dict[str, object]:
    args: dict[str, object] = {
        "cer": 0.02,
        "word_boundary": {"median_s": 0.1, "p95_s": 0.2},
        "selection": {"recall@5": 0.9},
    }
    args.update(overrides)
    return args


# ── 指标一：CER ──
def test_cer_identical_is_zero() -> None:
    assert qe.cer("苏明月", "苏明月") == 0.0


def test_cer_two_chars_both_wrong_is_one() -> None:
    # 传承→穿成：两字全变（替换 2 次）/ 2 字 = 1.0
    assert qe.cer("传承", "穿成") == 1.0


def test_cer_one_of_two_chars_wrong_is_half() -> None:
    # 传承→传成：1 字错 / 2 字 = 0.5
    assert qe.cer("传承", "传成") == 0.5


def test_cer_empty_reference_is_zero() -> None:
    """参考为空：分母 0，约定返回 0.0（无字数可错），不判 NaN。"""
    assert qe.cer("", "任意") == 0.0


def test_cer_empty_hypothesis_counts_full_distance() -> None:
    assert qe.cer("东厂", "") == 1.0


# ── 指标二：词界误差 ──
def test_word_boundary_zero_self_alignment() -> None:
    gold = [(0.0, 2.0), (2.0, 4.0), (4.0, 6.0)]
    out = qe.word_boundary_errors(gold, list(gold))
    assert out is not None
    assert out["median_s"] == 0.0 and out["p95_s"] == 0.0
    assert out["aligned"] == 3 and out["dropped"] == 0


def test_word_boundary_drift_detected() -> None:
    gold = [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, 4.0)]
    pred = [(0.2, 1.2), (1.5, 2.5), (2.0, 3.0), (3.9, 4.9)]
    out = qe.word_boundary_errors(gold, pred)
    assert out is not None
    # start 误差 0.2/0.5/0.0/0.9 → 中位 0.35，P95 取最大附近
    assert out["median_s"] == 0.35
    assert out["max_s"] == 0.9
    assert out["p95_s"] >= 0.5


def test_word_boundary_length_mismatch_reports_dropped() -> None:
    out = qe.word_boundary_errors([(0.0, 1.0), (1.0, 2.0)], [(0.0, 1.0)])
    assert out is not None
    assert out["aligned"] == 1
    assert out["dropped"] == 1


def test_word_boundary_empty_is_unknown() -> None:
    assert qe.word_boundary_errors([], []) is None
    assert qe.word_boundary_errors([(0.0, 1.0)], []) is None


# ── 指标三：选段 recall@k ──
def test_selection_recall_full_hit() -> None:
    gold = [
        {"episode": 1, "start": 0.0, "end": 12.5},
        {"episode": 1, "start": 24.0, "end": 38.0},
    ]
    predicted = [
        {"episode": 1, "start": 0.0, "end": 12.5},  # 命中 gold[0]
        {"episode": 1, "start": 24.0, "end": 38.0},  # 命中 gold[1]
    ]
    out = qe.selection_recall(gold, predicted, k=5)
    assert out is not None
    assert out["recall@5"] == 1.0
    assert out["hits"] == 2


def test_selection_recall_requires_same_episode() -> None:
    """跨集选段不算命中：同时间窗但集号不同 → 0 命中。"""
    gold = [{"episode": 1, "start": 0.0, "end": 12.5}]
    predicted = [{"episode": 2, "start": 0.0, "end": 12.5}]
    out = qe.selection_recall(gold, predicted, k=5)
    assert out is not None
    assert out["hits"] == 0
    assert out["recall@5"] == 0.0


def test_selection_recall_partial_overlap_counts() -> None:
    """重叠 ≥50% 较短窗才算命中：完全不相邻不命中。"""
    gold = [{"episode": 1, "start": 0.0, "end": 10.0}]
    predicted = [
        {"episode": 1, "start": 4.0, "end": 14.0},  # 重叠 6/10 ≥0.5 → 命中
        {"episode": 1, "start": 90.0, "end": 100.0},  # 无重叠 → 不命中
    ]
    out = qe.selection_recall(gold, predicted, k=5)
    assert out is not None
    assert out["hits"] == 1


def test_selection_recall_empty_gold_is_unknown() -> None:
    assert qe.selection_recall([], [{"episode": 1, "start": 0.0, "end": 1.0}]) is None


# ── 漂移门禁：算不出判 unknown，不静默判绿 ──
def test_drift_unknown_metrics_never_green() -> None:
    """缺指标（None）的项判 unknown，整体 all 不得为 pass（诚实纪律）。"""
    out = qe.evaluate_drift({"cer": None, "word_boundary": None, "selection": None})
    assert out["cer"] == "unknown"
    assert out["all"] != "pass"


def test_drift_all_pass_when_in_threshold() -> None:
    metrics = {
        "cer": 0.01,
        "word_boundary": {"median_s": 0.2, "p95_s": 0.5},
        "selection": {"recall@5": 0.8},
    }
    out = qe.evaluate_drift(metrics)
    assert out["all"] == "pass"


def test_drift_cer_over_threshold_fails() -> None:
    out = qe.evaluate_drift(_drift_args(cer=0.09))
    assert out["cer"] == "fail"
    assert out["all"] == "fail"


def test_drift_selection_recall_below_min_fails() -> None:
    out = qe.evaluate_drift(
        {
            "cer": 0.01,
            "word_boundary": {"median_s": 0.1, "p95_s": 0.2},
            "selection": {"recall@5": 0.3},
        }
    )
    assert out["selection_recall"] == "fail"
    assert out["all"] == "fail"


# ── 黄金集装配：缺字段不编造，算不出写 None ──
def test_load_golden_set_missing_files_is_honest(tmp_path: Path) -> None:
    """空目录：reference 空 → compute_metrics 的 cer/word/selection 全 None，不造数。"""
    golden = qe.load_golden_set(tmp_path)
    metrics = qe.compute_metrics(golden)
    assert metrics["cer"] is None
    assert metrics["word_boundary"] is None
    assert metrics["selection"] is None
    drift = qe.evaluate_drift(metrics)
    assert drift["all"] == "unknown"


def test_compute_metrics_self_aligned_golden_set(tmp_path: Path) -> None:
    """自对齐黄金集（word_gold=word_pred）：词界误差恒 0，门禁全绿。"""
    (tmp_path / "transcript.json").write_text(
        '[{"episode":1,"start":0.0,"end":12.5,"text":"苏明月，贱婢配进苏府？"}]',
        encoding="utf-8",
    )
    golden = qe.load_golden_set(tmp_path)
    metrics = qe.compute_metrics(golden)
    assert metrics["word_boundary"] is not None
    assert metrics["word_boundary"]["median_s"] == 0.0
    # 自对齐 cer 也应为 0（参考=假设）
    assert metrics["cer"] == 0.0


# ── CLI 端到端：--check 门禁语义 ──
def test_cli_check_self_aligned_golden_set_passes(tmp_path: Path) -> None:
    """自对齐黄金集过 --check：全指标在阈内 → 退 0。"""
    (tmp_path / "transcript.json").write_text(
        '[{"episode":1,"start":0.0,"end":12.5,"text":"苏明月，贱婢配进苏府？"}]',
        encoding="utf-8",
    )
    (tmp_path / "script_run.json").write_text(
        '{"output":{"segments":[{"episode":1,"start":0.0,"end":12.5,"text":"苏明月被斥贱婢"}]}}',
        encoding="utf-8",
    )
    assert qe.run_cli(["--fixtures", str(tmp_path), "--check"]) == 0


def test_cli_check_empty_fixtures_is_unknown_not_green(tmp_path: Path) -> None:
    """缺标注（空目录）：--check 退 0（unknown 不算 fail，绝不把量不出判成合格产品），
    且 all 为 unknown——不静默假绿。"""
    assert qe.run_cli(["--fixtures", str(tmp_path), "--check"]) == 0
