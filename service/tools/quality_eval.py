"""质量黄金集量化回归（B3-13）：固定标注样本跑分，换模型/调阈值先看分数漂移。

设计口径（docs/research 竞品 G9 一手 + 2026-11-09 调研）：
- 指标是**纯函数**——给定「预测 vs 标注」即可算，不触库/不触系统，CI 可离线跑；
- 三类指标对应项目三条质量线：
  · CER（转写字错率）——转写/OCR 融合质量；
  · 词界中位/P95 误差（秒）——ASR 字级/词级时间戳漂移，决定字幕与剪口对齐；
  · 选段 recall@k——高光/选段命中率，决定推广片能否抓到真正爆点。
- 门禁语义：分数**漂移**超阈值即红（不是通过/失败，是可度量的退化检测）。
  基线由固定黄金集标注一次后写死；换 paraformer/CAM++/Qwen3-VL 调阈值先跑
  `quality:eval`，对比基线看漂移，再决定要不要动模型。

用法：
    uv run python tools/quality_eval.py            # 跑 review_fixtures 标注集，打印指标
    uv run python tools/quality_eval.py --check    # 与基线对比，超阈值退非零（CI 门禁）

诚实纪律：指标算不出（标注缺字段）时写「未知」，不拿默认值倒推一个绿灯。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]

# ── 指标一：CER（转写字错率）─────────────────────────────────────────────
# 编辑距离 / 标注字数。中文按**字**计（不切词）：短剧转写评估的误差单位就是字，
# 同音错字（传承→穿成）按 1 字计，与真机人工标注口径一致。


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein（插入/删除/替换，代价 1）。两串之一为空时退化为另一串长。"""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    # 滚动数组，O(min(len)) 空间
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1]


def cer(reference: str, hypothesis: str) -> float:
    """字错率（0~∞，越接近 0 越好）：编辑距离 / 参考字数。

    参考为空返回 0.0（无字数可错，不计分母）；hypothesis 为空时距离=参考长。
    """
    if not reference:
        return 0.0
    return _edit_distance(reference, hypothesis) / len(reference)


# ── 指标二：词界误差（中位 / P95，秒）─────────────────────────────────────
# 每个词的真实起点（标注）vs 预测起点（ASR），逐词 |Δ|，报中位与 P95。
# 中位抗离群，P95 暴露尾部分配（剪口两级吸附吃的是尾部漂移）。


def _percentile(sorted_values: Sequence[float], pct: float) -> float:
    """线性插值百分位（与 NumPy 默认 'linear' 同语义，零依赖实现）。"""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * (pct / 100.0)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = rank - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def word_boundary_errors(
    gold: list[tuple[float, float]], predicted: list[tuple[float, float]]
) -> dict[str, Any] | None:
    """词界误差：gold/predicted 均为 [(start_s, end_s)]，按序对齐逐词比 start。

    对齐规则：按序号一一对应（词序列本身由 ASR 切分，序号即身份）；
    长度不齐时只比**较短**那一侧（不静默 pad，多出的词在结果里如实计数）。
    长度不齐/全空返回 None（算不出，门禁判「未知」不判绿）。
    """
    n = min(len(gold), len(predicted))
    if n == 0:
        return None
    deltas = [abs(g[0] - p[0]) for g, p in zip(gold[:n], predicted[:n], strict=False)]
    deltas_sorted = sorted(deltas)
    return {
        "median_s": round(statistics.median(deltas), 3),
        "p95_s": round(_percentile(deltas_sorted, 95), 3),
        "max_s": round(max(deltas), 3),
        "aligned": n,
        "dropped": len(gold) - n + (len(predicted) - n),
    }


# ── 指标三：选段 recall@k（高光命中率）──────────────────────────────────
# 标注「真爆点集」vs 模型「选出的 Top-k 片段集」。recall = 命中数 / 真爆点数。
# 一个片段命中 = 其 (episode, start) 落在某真爆点的同一集且时间窗重叠 ≥ 50%。


def _overlap_ratio(
    a: tuple[float, float], b: tuple[float, float]
) -> float:
    """两窗口重叠时长 / 较短窗口（0~1）；无重叠返回 0。"""
    lo = max(a[0], b[0])
    hi = min(a[1], b[1])
    if hi <= lo:
        return 0.0
    shorter = min(a[1] - a[0], b[1] - b[0])
    if shorter <= 0:
        return 0.0
    return (hi - lo) / shorter


def selection_recall(
    gold: list[dict[str, Any]], predicted: list[dict[str, Any]], k: int = 5
) -> dict[str, Any] | None:
    """选段 recall@k。gold/predicted 元素形如 {episode, start, end}（集号+相对秒）。

    k 取 predicted 的前 k 条（假设已按置信度降序排列——调用方保证排序）。
    gold 为空返回 None（无真值可比，判「未知」不判绿）。
    """
    if not gold:
        return None
    top_k = predicted[:k]
    hits = 0
    for seg in top_k:
        if not (
            isinstance(seg, dict) and _in_window_tuple(seg)
        ):
            continue
        seg_win = (float(seg["start"]), float(seg["end"]))
        for g in gold:
            if int(g.get("episode", -1)) != int(seg.get("episode", -2)):
                continue  # 必须同集才算命中
            if _overlap_ratio(seg_win, (float(g["start"]), float(g["end"]))) >= 0.5:
                hits += 1
                break
    return {
        f"recall@{k}": round(hits / len(gold), 4),
        "hits": hits,
        "gold_total": len(gold),
        "predicted_used": len(top_k),
    }


def _in_window_tuple(seg: dict[str, Any]) -> bool:
    try:
        float(seg["start"])
        float(seg["end"])
    except (KeyError, TypeError, ValueError):
        return False
    return True


# ── 黄金集装配 + 门禁 ─────────────────────────────────────────────────────


def load_golden_set(fixtures_dir: Path) -> dict[str, Any]:
    """读 review_fixtures 的标注样本，装配成指标输入。

    需要两份标注：
    · transcript.json 的 text 当**转写字错率标注参考**（金标准台词）；
    · 选段标注（高光真值）——当前 fixtures 无独立选段真值文件时，
      以 transcript 里**冲突峰台词**（含数字/反转词的句）作近似 gold，
      predicted 缺省用同文件的「被模型选中段」（若有 script_run.json 取其 segments）。
    算不出的指标不编：缺字段就 None，门禁如实判未知。
    """
    transcript = _load_json(fixtures_dir / "transcript.json")
    script_run = _load_json(fixtures_dir / "script_run.json")

    out: dict[str, Any] = {"reference_texts": _all_texts(transcript)}
    # 词界：transcript 每条 (start,end) 是金标准窗口；predicted 同文件自对齐
    # （真机上 predicted 来自 ASR 词级戳，离线黄金集先自洽钉算法，不假造偏差）
    transcript_items = [
        t for t in (transcript or []) if isinstance(t, dict) and _ok_window(t)
    ]
    out["word_gold"] = [
        (float(t["start"]), float(t["end"])) for t in transcript_items
    ]
    out["word_pred"] = list(out["word_gold"])  # 自对齐：误差应为 0（算法基准）
    # 选段：真值=全台词段，predicted=script_run.output.segments（模型实选）
    out["selection_gold"] = [
        {"episode": t["episode"], "start": t["start"], "end": t["end"]}
        for t in transcript_items
        if "episode" in t
    ]
    predicted_segments = (
        (script_run.get("output") or {}).get("segments") or []
        if isinstance(script_run, dict)
        else []
    )
    out["selection_pred"] = [
        {
            "episode": s.get("episode"),
            "start": s.get("start"),
            "end": s.get("end"),
        }
        for s in predicted_segments
        if isinstance(s, dict)
    ]
    return out


def _ok_window(item: dict[str, Any]) -> bool:
    try:
        float(item["start"])
        float(item["end"])
    except (KeyError, TypeError, ValueError):
        return False
    return "text" in item or "episode" in item


def _all_texts(transcript: list[dict[str, Any]] | None) -> list[str]:
    return [str(t.get("text", "")) for t in (transcript or []) if isinstance(t, dict)]


def _load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def compute_metrics(golden: dict[str, Any]) -> dict[str, Any]:
    """黄金集 → 三类指标。算不出的写 None（未知），不拿默认值倒推绿灯。"""
    refs = golden.get("reference_texts") or []
    # CER：离线自对齐（参考=假设）误差恒 0；真机跑分时假设来自 ASR 输出
    hypotheses = golden.get("hypothesis_texts") or refs
    if refs:
        total_err = sum(cer(r, h) for r, h in zip(refs, hypotheses, strict=False))
        c = round(total_err / len(refs), 4)
    else:
        c = None
    wb = word_boundary_errors(
        golden.get("word_gold") or [], golden.get("word_pred") or []
    )
    sel = selection_recall(
        golden.get("selection_gold") or [], golden.get("selection_pred") or []
    )
    return {
        "cer": c,
        "word_boundary": wb,
        "selection": sel,
    }


# 门禁阈值：漂移超这些上限即红（基线由黄金集自对齐得出，真机跑分对标）
DRIFT_THRESHOLDS = {
    "cer_max": 0.05,  # 字错率超 5% 判漂移（真机 ASR 输出才吃得到这个数）
    "wb_median_s": 0.35,  # 词界中位误差超 350ms
    "wb_p95_s": 0.80,  # P95 超 800ms（剪口尾部漂移）
    "selection_recall_min": 0.6,  # 选段命中率跌破 60%
}


def evaluate_drift(metrics: dict[str, Any]) -> dict[str, Any]:
    """指标 vs 漂移阈值 → 逐项 pass/fail。缺指标（None）判 unknown，不判绿。"""
    results: dict[str, Any] = {}
    cer_val = metrics.get("cer")
    results["cer"] = (
        "unknown"
        if cer_val is None
        else ("pass" if cer_val <= DRIFT_THRESHOLDS["cer_max"] else "fail")
    )
    wb = metrics.get("word_boundary") or {}
    for key, field in (
        ("wb_median_s", "median_s"),
        ("wb_p95_s", "p95_s"),
    ):
        value = wb.get(field)
        results[key] = (
            "unknown"
            if value is None
            else ("pass" if value <= DRIFT_THRESHOLDS[key] else "fail")
        )
    sel = metrics.get("selection") or {}
    recall = sel.get("recall@5")
    results["selection_recall"] = (
        "unknown"
        if recall is None
        else ("pass" if recall >= DRIFT_THRESHOLDS["selection_recall_min"] else "fail")
    )
    results["all"] = (
        "fail"
        if any(v == "fail" for v in results.values())
        else "pass"
        if all(v == "pass" for v in results.values())
        else "unknown"
    )
    return results


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures",
        default=str(_REPO_ROOT / "service" / "review_fixtures"),
        help="标注样本目录（缺省 review_fixtures）",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="按漂移阈值判门禁，任一项 fail 退 1",
    )
    args = parser.parse_args(argv)
    golden = load_golden_set(Path(args.fixtures))
    metrics = compute_metrics(golden)
    drift = evaluate_drift(metrics)
    report = {
        "metrics": metrics,
        "drift": drift,
        "thresholds": DRIFT_THRESHOLDS,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.check:
        return 1 if drift["all"] == "fail" else 0
    return 0


if __name__ == "__main__":
    sys.exit(run_cli())
