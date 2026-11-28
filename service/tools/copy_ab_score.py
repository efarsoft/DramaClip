"""独立打分协议与裁判校准统计：每篇稿单独打分，量裁判稳不稳、两个裁判有没有共识。

为什么另起一套：两两盲评受位置偏好影响（试点实测某裁判 24 次判决里 18 次选后呈现的那篇）。
独立打分一次只看一篇，从根上没有位置可比；代价是绝对分比两两比较粗——所以先量它自己
稳不稳（同一篇打两次一不一致）、两个模型对同一批稿子有没有共识，再决定能不能当尺子。

本模块只放打分协议与统计；调用模型、落盘、并发都在 tools/copy_ab.py（经 run_scores 接入）。
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from dramaclip.engines.semantic.llm_client import LlmClient, redact_secrets
from tools.copy_ab_core import VARIANT_A, VARIANT_B, Script, plain_density, quote_found

SCORE_SYSTEM = (
    "你是刷短视频的普通观众，没看过这部剧。下面是一篇短剧解说视频的文字稿。"
    "假设你划到这条视频、听到了这些话：给它打 1–10 分，分数只回答一件事——"
    "你有多想继续看下去、点进去看全集。"
    "10=立刻想点进去；7=有点想；5=可看可不看；3=想划走；1=完全不想看。\n"
    "要求：不猜是谁写的、不评价写作方法；篇幅长短不是理由；引一句原文说明最影响你判断的地方。\n"
    '只输出 JSON：{"score": 1 到 10 的整数, "quote": "原句", "reason": "一句话"}'
)
SCORE_USER = "{text}\n\n这篇解说你想看下去吗？打几分？"

# ── 尺子的合格线（跑之前登记）──
RETEST_R_MIN = 0.70  # 同一篇两次打分的相关下限：自己跟自己都对不上的裁判不能用
AGREEMENT_R_MIN = 0.50  # 两个裁判对同一批稿子均分的相关下限：毫无共识说明分数多半是噪声


@dataclass(frozen=True)
class ScoreRow:
    script_id: str
    sample_id: str
    variant: str
    judge: str
    repeat: int
    score: int  # 1–10；0=无效
    quote_ok: bool
    quote: str
    reason: str
    error: str  # 非空=本次打分无效（调用失败或输出不合约定）


def parse_score(raw: Any) -> tuple[int, str, str] | None:
    """裁判输出 → (分数, 引文, 理由)；分数不是 1–10 的整数或形状不对返回 None。"""
    if not isinstance(raw, dict):
        return None
    score = raw.get("score")
    if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 10:
        return None
    return score, str(raw.get("quote") or "").strip(), str(raw.get("reason") or "").strip()


def score_script(client: LlmClient, script: Script, judge: str, repeat: int) -> ScoreRow:
    """给一篇稿打一次分：输出不合约定换温度再试一次，仍不合就记无效。"""
    user = SCORE_USER.format(text=script.text)
    error = ""
    for temperature in (0.3, 0.7):
        try:
            parsed = parse_score(client.chat_json(SCORE_SYSTEM, user, temperature=temperature))
        except Exception as exc:  # noqa: BLE001 - 记成无效打分；连续无效由调用方熔断
            error = redact_secrets(f"{type(exc).__name__}: {exc}")[:300]
            continue
        if parsed is None:
            error = "裁判输出不合约定"
            continue
        score, quote, reason = parsed
        return ScoreRow(
            script.script_id,
            script.sample_id,
            script.variant,
            judge,
            repeat,
            score,
            quote_found(quote, script.text),
            quote,
            reason,
            "",
        )
    return ScoreRow(
        script.script_id, script.sample_id, script.variant, judge, repeat, 0, False, "", "", error
    )


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """皮尔逊相关；不足三对或任一侧全相等返回 None（算不出≠0）。"""
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    mean_x, mean_y = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((x - mean_x) ** 2 for x in xs)
    syy = sum((y - mean_y) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return round(
        sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
        / math.sqrt(sxx * syy),
        3,
    )


def ranks(values: Sequence[float]) -> list[float]:
    """并列取平均名次（1 起）。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        for position in range(start, end + 1):
            out[order[position]] = (start + end) / 2 + 1
        start = end + 1
    return out


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    return pearson(ranks(xs), ranks(ys))


@dataclass(frozen=True)
class JudgeStat:
    judge: str
    scripts: int
    mean: float
    sd: float
    retest_r: float | None  # 同一篇两次打分的相关
    reliability: float | None  # 稿间方差 /（稿间方差 + 稿内方差）
    mean_a: float | None
    mean_b: float | None
    samples_b_ahead: int  # B 均分高于 A 的样本数
    samples: int
    density_rho: float | None  # 直白情绪词密度与均分的秩相关
    density_rho_within: float | None  # 样本内各自排名后去掉样本均值再合并


def _script_means(rows: Sequence[Mapping[str, Any]], judge: str) -> dict[str, list[int]]:
    scores: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        if row.get("judge") == judge and not row.get("error") and int(row.get("score") or 0) > 0:
            scores[str(row["script_id"])].append(int(row["score"]))
    return dict(scores)


def _within_sample_rho(
    ids_by_sample: Mapping[str, Sequence[str]], x_of: Mapping[str, float], y_of: Mapping[str, float]
) -> float | None:
    """样本内排名、各减样本均名次后合并求相关：题材带来的整体高低被消掉，只看同一题材里的排序。"""
    xs: list[float] = []
    ys: list[float] = []
    for ids in ids_by_sample.values():
        if len(ids) < 3:
            continue
        rank_x, rank_y = ranks([x_of[i] for i in ids]), ranks([y_of[i] for i in ids])
        mean_x, mean_y = statistics.mean(rank_x), statistics.mean(rank_y)
        xs.extend(value - mean_x for value in rank_x)
        ys.extend(value - mean_y for value in rank_y)
    return pearson(xs, ys) if len(xs) >= 3 else None


def judge_stats(
    rows: Sequence[Mapping[str, Any]],
    judge: str,
    scripts: Sequence[Script],
) -> JudgeStat | None:
    """一个裁判在这批稿子上的稳定度与分辨力；顺带给出 A/B 均分与「密度—评分」相关。"""
    scores = _script_means(rows, judge)
    if not scores:
        return None
    means = {script_id: statistics.mean(values) for script_id, values in scores.items()}
    repeated = [values for values in scores.values() if len(values) >= 2]
    retest = (
        pearson([float(v[0]) for v in repeated], [float(v[1]) for v in repeated])
        if len(repeated) >= 3
        else None
    )
    within = [statistics.variance(values) for values in repeated]
    reliability = None
    if len(means) >= 3 and within:
        repeats_mean = statistics.mean(len(values) for values in scores.values())
        between = statistics.variance(list(means.values()))
        reliability = round(between / (between + statistics.mean(within) / repeats_mean), 3)
    meta_of = {script.script_id: script for script in scripts}
    by_variant: dict[str, list[float]] = defaultdict(list)
    by_sample: dict[str, list[float]] = defaultdict(list)
    for script_id, value in means.items():
        script = meta_of.get(script_id)
        if script is None:
            continue
        by_variant[script.variant].append(value)
        by_sample[script.sample_id].append(value)
    samples = sorted({script.sample_id for script in scripts if script.script_id in means})
    ahead = 0
    for sample in samples:
        a = [
            means[s.script_id]
            for s in scripts
            if s.sample_id == sample and s.variant == VARIANT_A and s.script_id in means
        ]
        b = [
            means[s.script_id]
            for s in scripts
            if s.sample_id == sample and s.variant == VARIANT_B and s.script_id in means
        ]
        if a and b and statistics.mean(b) > statistics.mean(a):
            ahead += 1
    density = {
        script.script_id: plain_density(script) for script in scripts if script.script_id in means
    }
    ids = sorted(density)
    ids_by_sample: dict[str, list[str]] = defaultdict(list)
    for script in scripts:
        if script.script_id in density:
            ids_by_sample[script.sample_id].append(script.script_id)
    return JudgeStat(
        judge=judge,
        scripts=len(means),
        mean=round(statistics.mean(means.values()), 2),
        sd=round(statistics.pstdev(list(means.values())), 2),
        retest_r=retest,
        reliability=reliability,
        mean_a=round(statistics.mean(by_variant[VARIANT_A]), 2) if by_variant[VARIANT_A] else None,
        mean_b=round(statistics.mean(by_variant[VARIANT_B]), 2) if by_variant[VARIANT_B] else None,
        samples_b_ahead=ahead,
        samples=len(samples),
        density_rho=spearman([density[i] for i in ids], [means[i] for i in ids])
        if len(ids) >= 3
        else None,
        density_rho_within=_within_sample_rho(ids_by_sample, density, means),
    )


def judges_agreement(rows: Sequence[Mapping[str, Any]], judge_a: str, judge_b: str) -> float | None:
    """两个裁判在都打过的稿子上的均分相关。"""
    means_a = _script_means(rows, judge_a)
    means_b = _script_means(rows, judge_b)
    shared = sorted(set(means_a) & set(means_b))
    if len(shared) < 3:
        return None
    return pearson(
        [statistics.mean(means_a[i]) for i in shared], [statistics.mean(means_b[i]) for i in shared]
    )


def position_stats(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """两两判决的位置分布：选先呈现/后呈现/差不多各几次，换位后两次选同一篇的比例。"""
    valid = [row for row in rows if not row.get("error")]
    first = sum(1 for row in valid if row.get("picked_id") and row["picked_id"] == row["first_id"])
    second = sum(1 for row in valid if row.get("picked_id") and row["picked_id"] != row["first_id"])
    picks: dict[str, set[str]] = defaultdict(set)
    for row in valid:
        picks[str(row["pair_id"])].add(str(row.get("picked_id") or ""))
    consistent = sum(1 for values in picks.values() if len(values) == 1 and "" not in values)
    return {
        "valid": len(valid),
        "first": first,
        "second": second,
        "even": len(valid) - first - second,
        "pairs": len(picks),
        "consistent": consistent,
    }


def _fmt(value: float | None) -> str:
    return "算不出" if value is None else f"{value:.2f}"


def _pct(numerator: int, denominator: int) -> str:
    return f"{numerator / denominator:.0%}" if denominator else "算不出"


def render_score_report(
    stats: Sequence[JudgeStat],
    agreement: Mapping[tuple[str, str], float | None],
    positions: Mapping[str, dict[str, Any]],
) -> str:
    """裁判校准页：每个裁判的重测相关/分辨力/两裁判共识，再用合格线逐条判。"""
    lines = [
        "# 裁判校准（独立打分）",
        "",
        f"合格线（跑前登记）：同一篇两次打分相关 ≥ {RETEST_R_MIN}；两裁判均分相关 ≥ {AGREEMENT_R_MIN}。",
        "",
        "| 裁判 | 稿数 | 均分 | 标准差 | 重测相关 | 分辨力 | 过线 |",
        "|---|---|---|---|---|---|---|",
    ]
    for stat in stats:
        ok = stat.retest_r is not None and stat.retest_r >= RETEST_R_MIN
        lines.append(
            f"| {stat.judge} | {stat.scripts} | {stat.mean} | {stat.sd} | {_fmt(stat.retest_r)} | "
            f"{_fmt(stat.reliability)} | {'过' if ok else '不过'} |"
        )
    lines += ["", "## 两裁判共识", ""]
    for (judge_a, judge_b), value in agreement.items():
        ok = value is not None and value >= AGREEMENT_R_MIN
        lines.append(f"- {judge_a} × {judge_b}：均分相关 {_fmt(value)}（{'过' if ok else '不过'}）")
    lines += ["", "## 顺带读数（探索性，不作结论）", ""]
    for stat in stats:
        lines.append(
            f"- {stat.judge}：A 版均分 {stat.mean_a} / B 版均分 {stat.mean_b}；"
            f"B 高于 A 的样本 {stat.samples_b_ahead}/{stat.samples}；"
            f"直白情绪词密度与评分的秩相关 {_fmt(stat.density_rho)}，样本内 {_fmt(stat.density_rho_within)}"
        )
    lines += ["", "## 两两判决的位置分布（只看同版对同版）", ""]
    for judge, row in positions.items():
        lines.append(
            f"- {judge}：有效判决 {row['valid']}，选先呈现 {row['first']} / 选后呈现 {row['second']} / "
            f"差不多 {row['even']}；换位后两次选同一篇 {_pct(row['consistent'], row['pairs'])}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 接入（并发与落盘由 tools/copy_ab.py 的通用并发器提供）
# ---------------------------------------------------------------------------

Item = tuple[Script, int]


def register_commands(
    sub: Any,
    add_db: Callable[[Any], None],
    score_cmd: Callable[[Any], int],
    score_report_cmd: Callable[[Any], int],
) -> None:
    """把 score / score-report 两个子命令挂到主解析器上（实参在 tools/copy_ab.py）。"""
    pc = sub.add_parser("score", help="独立打分：每篇单独打 1–10 分（没有位置问题）")
    add_db(pc)
    pc.add_argument("--run", required=True, help="运行目录")
    pc.add_argument("--judge", required=True, help="裁判端点的配置名（引擎页里的名称）")
    pc.add_argument("--judge-model", default="", help="换用同一端点上的另一个模型")
    pc.add_argument("--tag", default="", help="结果文件与统计表里的裁判名（默认取模型名）")
    pc.add_argument("--repeats", type=int, default=2, help="每篇打几次（默认 2，量重测相关）")
    pc.add_argument("--workers", type=int, default=4, help="并发路数（默认 4）")
    pc.set_defaults(func=score_cmd)

    pr = sub.add_parser("score-report", help="裁判校准页：稳不稳、有没有共识、位置偏不偏")
    pr.add_argument("--run", required=True, help="运行目录")
    pr.set_defaults(func=score_report_cmd)


def pending_scores(
    scripts: Sequence[Script], repeats: int, done: set[tuple[str, int]]
) -> list[Item]:
    return [
        (script, repeat)
        for script in scripts
        for repeat in range(1, repeats + 1)
        if (script.script_id, repeat) not in done
    ]


def score_work(judge: str) -> Callable[[Item, LlmClient], ScoreRow]:
    def work(item: Item, client: LlmClient) -> ScoreRow:
        script, repeat = item
        return score_script(client, script, judge, repeat)

    return work


def score_label(row: ScoreRow) -> str:
    outcome = f"无效：{row.error}" if row.error else f"{row.score} 分"
    return f"{row.script_id} 第 {row.repeat} 次 → {outcome}"
