"""评审分趟对照实验（离线工具）：造对照稿 → 几个评审各评一遍 → 尺子打分 → 结论页。

四个评审评的是同一批稿子（本机生产模型那把钥匙，与线上评分器同一个端点）：
  current_batch   现状：同一篇原稿的四份一组、带「方案 N」标签，一次调用打六维
  current_single  现状：一稿一次调用打六维（线上 `score_one` 走的就是这条）
  quoted          对照：一稿一次调用打六维，但必须逐维带引文、不带标签
  staged          分趟：开头/中段/结尾各只看自己那一段、一趟一个判据、必须带引文，
                  整篇再评冲突可懂度/情绪/画面三维
尺子（另一个家族的模型）对每篇稿独立打分，协议与校准见 copy_ab_score。

纯函数都在 tools/review_ab_core.py；钥匙只由本机库直读进内存，产物在运行目录（data/ 不进仓库）。

子命令（都要 --run 运行目录；--db 默认本机库）：
  build   --run DIR --ab-run DIR [--per-sample 2]       从 A/B 出稿里挑原稿，造四份一组的对照稿
  yard    --run DIR --judge 配置名 [--judge-model 模型] 尺子独立打分（每篇两次）
  score   --run DIR --scorer NAME [--workers N]         某个评审评一遍（已评过的跳过）
  report  --run DIR                                         结论页
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dramaclip.engines import llm_prompts  # noqa: E402
from dramaclip.engines.narration import variant_scoring  # noqa: E402
from dramaclip.engines.semantic.llm_client import (  # noqa: E402
    LlmClient,
    LlmUnavailable,
    redact_secrets,
)
from tools import copy_ab  # noqa: E402
from tools import copy_ab_score as scoring  # noqa: E402
from tools import review_ab_core as core  # noqa: E402
from tools.copy_ab_core import Script  # noqa: E402

SCORERS: tuple[str, ...] = ("current_batch", "current_single", "quoted", "staged")
PASSES: tuple[str, ...] = ("hook", "middle", "ending", "whole")
#: 分趟里每个局部趟该认的那种坏（结论页里分趟自己的分差按这个对）
PASS_SPOTS: dict[str, str] = {
    "hook": core.PAD_OPEN,
    "ending": core.FLAT_END,
    "middle": core.SHUFFLE_MID,
}


@dataclass
class Scored:
    """一个评审对一篇稿子的结论。"""

    scorer: str
    item_id: str
    base: str
    cond: str
    total: float = 0.0
    dims: dict[str, Any] = field(default_factory=dict)
    detail: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass
class Grouped:
    """整批评分对一组（同一篇原稿的四份）的结论：只带原稿那一份的分，其余在 detail。"""

    item_id: str
    base: str
    cond: str
    total: float = 0.0
    dims: dict[str, Any] = field(default_factory=dict)
    detail: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass
class Passed:
    """分趟里的一趟。"""

    pass_name: str
    item_id: str
    base: str
    cond: str
    score: float = 0.0
    quote: str = ""
    fix: str = ""
    dims: dict[str, float] = field(default_factory=dict)
    error: str = ""


# ---------------------------------------------------------------------------
# 运行目录读写
# ---------------------------------------------------------------------------


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _write_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(dict(row), ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _items(run_dir: Path) -> list[core.Item]:
    return [
        core.Item(str(row["item_id"]), str(row["base"]), str(row["cond"]), tuple(row["texts"]))
        for row in _rows(run_dir / "items.jsonl")
    ]


def _settled(path: Path, key: Callable[[Mapping[str, Any]], Any]) -> set[Any]:
    """已评出有效结果的条目键：重跑时跳过。"""
    return {key(row) for row in _rows(path) if not row.get("error")}


def _label(row: Scored) -> str:
    outcome = f"无效：{row.error}" if row.error else f"{row.total:.1f} 分"
    return f"{row.item_id} → {outcome}"


def _group_label(row: Grouped) -> str:
    outcome = f"无效：{row.error}" if row.error else "已评"
    return f"{row.item_id} 那一组 → {outcome}"


def _pass_label(row: Passed) -> str:
    if row.error:
        return f"{row.item_id} [{row.pass_name}] → 无效：{row.error}"
    shown = (
        f"{row.score:.0f} 分"
        if row.score
        else "、".join(f"{k} {v:.0f}" for k, v in row.dims.items())
    )
    return f"{row.item_id} [{row.pass_name}] → {shown}"


# ---------------------------------------------------------------------------
# 调模型：两次机会，输出不合约定换温度再试
# ---------------------------------------------------------------------------


def _ask(
    client: LlmClient, system: str, user: str, parse: Callable[[Any], dict[str, Any] | None]
) -> tuple[dict[str, Any] | None, str]:
    error = ""
    for temperature in (0.3, 0.7):
        try:
            raw = client.chat_json(system, user, temperature=temperature)
        except Exception as exc:  # noqa: BLE001 - 记成无效；连续无效由并发器熔断
            error = redact_secrets(f"{type(exc).__name__}: {exc}")[:300]
            continue
        parsed = parse(raw)
        if parsed is not None:
            return parsed, ""
        error = "输出不合约定"
    return None, error


def _system_of(settings: Mapping[str, str]) -> str:
    return (
        llm_prompts.system_override(settings, "prompt.variant_scoring_system")
        or variant_scoring._SYSTEM_PROMPT
    )


def _plan_row(item: core.Item) -> dict[str, Any]:
    """与线上方案行同形：喂给生产评分器的措辞与解析都原样复用。"""
    return {
        "id": item.item_id,
        "angle": "",
        "plan_data": {"narration_texts": [{"text": text} for text in item.texts]},
    }


def current_single_work(settings: Mapping[str, str]) -> Callable[[core.Item, LlmClient], Scored]:
    """现状的单稿评分：生产提示词、生产措辞、生产解析，一条不改。"""
    system = _system_of(settings)

    def work(item: core.Item, client: LlmClient) -> Scored:
        error = ""
        for _ in range(2):
            try:
                raw = client.chat_json(system, variant_scoring.format_variant(1, _plan_row(item)))
                entry = variant_scoring._parse_batch(raw, 1)[1]
            except (LlmUnavailable, ValueError, TypeError, KeyError) as exc:
                error = redact_secrets(f"{type(exc).__name__}: {exc}")[:300]
                continue
            return Scored(
                "current_single",
                item.item_id,
                item.base,
                item.cond,
                entry["total"],
                dict(entry["dims"]),
                {"suggestion": entry["suggestion"]},
            )
        return Scored("current_single", item.item_id, item.base, item.cond, error=error)

    return work


def current_batch_work(
    settings: Mapping[str, str],
) -> Callable[[Sequence[core.Item]], Grouped]:
    """现状的整批评分：一次调用评同一篇原稿的四份，带「方案 N」标签。"""

    def work(group: Sequence[core.Item], client: LlmClient) -> Grouped:
        system = _system_of(settings)
        user = "\n\n".join(
            variant_scoring.format_variant(index, _plan_row(item))
            for index, item in enumerate(group, start=1)
        )
        plain = next(item for item in group if item.cond == core.PLAIN)
        error = ""
        for _ in range(2):
            try:
                raw = client.chat_json(system, user)
                scored = variant_scoring._parse_batch(raw, expected=len(group))
            except (LlmUnavailable, ValueError, TypeError, KeyError) as exc:
                error = redact_secrets(f"{type(exc).__name__}: {exc}")[:300]
                continue
            entries = {
                item.cond: scored[index]
                for index, item in enumerate(group, start=1)
                if index in scored
            }
            head = entries[plain.cond]
            return Grouped(
                plain.item_id,
                plain.base,
                plain.cond,
                head["total"],
                dict(head["dims"]),
                {"group": entries},
            )
        return Grouped(plain.item_id, plain.base, plain.cond, error=error)

    return work


def quoted_work(all_anchors: Mapping[str, str]) -> Callable[[core.Item, LlmClient], Scored]:
    system = core.quoted_system(all_anchors)

    def work(item: core.Item, client: LlmClient) -> Scored:
        parsed, error = _ask(
            client, system, item.text, lambda raw: core.parse_quoted(raw, item.text)
        )
        if parsed is None:
            return Scored("quoted", item.item_id, item.base, item.cond, error=error)
        return Scored(
            "quoted",
            item.item_id,
            item.base,
            item.cond,
            variant_scoring.weighted_total(parsed["dims"]),
            dict(parsed["dims"]),
            {"quotes": parsed["quotes"], "suggestion": parsed["suggestion"]},
        )

    return work


def staged_work(
    all_anchors: Mapping[str, str],
) -> Callable[[tuple[core.Item, str], LlmClient], Passed]:
    local = {
        name: core.local_system(dim, all_anchors[dim])
        for name, dim, _part, _focus in core._LOCAL_DIMS
    }
    whole = core.whole_system(all_anchors)

    def work(job: tuple[core.Item, str], client: LlmClient) -> Passed:
        item, name = job
        if name == "whole":
            parsed, error = _ask(
                client, whole, item.text, lambda raw: core.parse_whole(raw, item.text)
            )
            if parsed is None:
                return Passed(name, item.item_id, item.base, item.cond, error=error)
            return Passed(name, item.item_id, item.base, item.cond, dims=dict(parsed["dims"]))
        opening, middle, ending = core.local_parts(item.texts)
        # 稿子太短没有中段：拿整篇当它的中段评，不因缺料让这一维作废
        excerpt = {"hook": opening, "middle": middle or item.text, "ending": ending}[name]
        parsed, error = _ask(
            client, local[name], excerpt, lambda raw: core.parse_local(raw, excerpt)
        )
        if parsed is None:
            return Passed(name, item.item_id, item.base, item.cond, error=error)
        return Passed(
            name,
            item.item_id,
            item.base,
            item.cond,
            parsed["score"],
            parsed["quote"],
            parsed["fix"],
        )

    return work


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------


def cmd_build(args: argparse.Namespace) -> int:
    ab_dir = Path(args.ab_run)
    texts_of = {
        script.script_id: script.texts for script in copy_ab._load_scripts(ab_dir) if script.ok
    }
    yard_of: dict[str, list[float]] = {}
    for path in sorted(ab_dir.glob("scores_*.jsonl")):
        for row in _rows(path):
            if not row.get("error"):
                yard_of.setdefault(str(row["script_id"]), []).append(float(row["score"]))
    means = {key: sum(values) / len(values) for key, values in yard_of.items()}
    picked = core.pick_bases(texts_of, means, args.per_sample)
    items = core.build_items(picked)
    run_dir = Path(args.run)
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_rows(run_dir / "items.jsonl", [asdict(item) for item in items])
    print(
        f"原稿 {len(picked)} 篇 × {len(core.CONDITIONS)} 份 → 对照稿 {len(items)} 篇："
        f"{', '.join(picked)}",
        flush=True,
    )
    return 0


def cmd_yard(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    judge_settings, model = copy_ab._judge_endpoint(args)
    judge = args.tag.strip() or model
    scripts = [
        Script(
            script_id=item.item_id,
            sample_id=item.base,
            variant=item.cond,
            index=0,
            ok=True,
            texts=item.texts,
            dropped=0,
            error="",
        )
        for item in _items(run_dir)
    ]
    out_path = run_dir / f"scores_{judge}.jsonl"
    done = {
        (str(row["script_id"]), int(row["repeat"]))
        for row in _rows(out_path)
        if not row.get("error")
    }
    pending = scoring.pending_scores(scripts, args.repeats, done)
    print(
        f"尺子 {judge}（{model}）：{len(scripts)} 篇 × {args.repeats} 次，待打 {len(pending)}",
        flush=True,
    )
    return copy_ab._run_parallel(
        judge_settings,
        pending,
        out_path,
        args.workers,
        scoring.score_work(judge),
        scoring.score_label,
    )


def _score_current_batch(run_dir: Path, settings: Mapping[str, str], workers: int) -> int:
    """整批评分：一次调用评一组，只把每组交给并发器；四份的结论随后从 detail 里拆出来。"""
    groups: dict[str, list[core.Item]] = {}
    for item in _items(run_dir):
        groups.setdefault(item.base, []).append(item)
    out_path = run_dir / "scored_current_batch.jsonl"
    done = _settled(out_path, lambda row: str(row["item_id"]))
    pending = [group for group in groups.values() if group[0].item_id not in done]
    print(f"current_batch：{len(groups)} 组，待评 {len(pending)}（{workers} 路并发）", flush=True)
    copy_ab._run_parallel(
        settings, pending, out_path, workers, current_batch_work(settings), _group_label
    )
    expanded = [
        Scored(
            "current_batch",
            f"{row['base']}-{cond}",
            str(row["base"]),
            cond,
            float(entry["total"]),
            dict(entry["dims"]),
            {"group_of": str(row["item_id"])},
        )
        for row in _rows(out_path)
        if not row.get("error")
        for cond, entry in (row.get("detail") or {}).get("group", {}).items()
    ]
    _write_rows(run_dir / "scored_current_batch_all.jsonl", [asdict(row) for row in expanded])
    print(f"拆出四份的结论 {len(expanded)} 条 → scored_current_batch_all.jsonl", flush=True)
    return 0


def _score_singles(run_dir: Path, settings: Mapping[str, str], workers: int) -> int:
    out_path = run_dir / "scored_current_single.jsonl"
    done = _settled(out_path, lambda row: str(row["item_id"]))
    pending = [item for item in _items(run_dir) if item.item_id not in done]
    print(f"current_single：待评 {len(pending)}（{workers} 路并发）", flush=True)
    return copy_ab._run_parallel(
        settings, pending, out_path, workers, current_single_work(settings), _label
    )


def _score_quoted(run_dir: Path, settings: Mapping[str, str], workers: int) -> int:
    out_path = run_dir / "scored_quoted.jsonl"
    done = _settled(out_path, lambda row: str(row["item_id"]))
    pending = [item for item in _items(run_dir) if item.item_id not in done]
    print(f"quoted：待评 {len(pending)}（{workers} 路并发）", flush=True)
    return copy_ab._run_parallel(
        settings, pending, out_path, workers, quoted_work(core.anchors()), _label
    )


def _score_staged(run_dir: Path, settings: Mapping[str, str], workers: int) -> int:
    out_path = run_dir / "passes_staged.jsonl"
    done = _settled(out_path, lambda row: (str(row["item_id"]), str(row["pass_name"])))
    pending = [
        (item, name)
        for item in _items(run_dir)
        for name in PASSES
        if (item.item_id, name) not in done
    ]
    print(f"staged：待评 {len(pending)} 趟（{workers} 路并发）", flush=True)
    return copy_ab._run_parallel(
        settings, pending, out_path, workers, staged_work(core.anchors()), _pass_label
    )


def cmd_score(args: argparse.Namespace) -> int:
    scorer = args.scorer
    if scorer not in SCORERS:
        raise SystemExit(f"--scorer 只认 {'、'.join(SCORERS)}")
    conn = copy_ab._connect(Path(args.db))
    settings = copy_ab._load_settings(conn)
    conn.close()
    run_dir = Path(args.run)
    runners: dict[str, Callable[[Path, Mapping[str, str], int], int]] = {
        "current_batch": _score_current_batch,
        "current_single": _score_singles,
        "quoted": _score_quoted,
        "staged": _score_staged,
    }
    return runners[scorer](run_dir, settings, args.workers)


def _verdicts(rows: Sequence[Mapping[str, Any]], scorer: str) -> list[core.Verdict]:
    return [
        core.Verdict(
            scorer,
            str(row["item_id"]),
            str(row["base"]),
            str(row["cond"]),
            float(row["total"]),
            dict(row.get("dims") or {}),
        )
        for row in rows
        if not row.get("error")
    ]


def _pass_gaps(passes: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, float]]:
    """分趟里每个局部趟，对它该认的那种坏给出的平均分差（原稿 − 对照稿）。"""
    gaps: dict[str, dict[str, float]] = {}
    for name, matched in PASS_SPOTS.items():
        rows = [row for row in passes if row["pass_name"] == name and not row.get("error")]
        plain = {str(row["base"]): row for row in rows if row["cond"] == core.PLAIN}
        deltas = [
            float(plain[str(row["base"])]["score"]) - float(row["score"])
            for row in rows
            if row["cond"] == matched and str(row["base"]) in plain
        ]
        if deltas:
            gaps[name] = {matched: round(sum(deltas) / len(deltas), 2)}
    return gaps


def _staged_verdicts(run_dir: Path, passes: Sequence[Mapping[str, Any]]) -> list[core.Verdict]:
    items_by_id = {item.item_id: item for item in _items(run_dir)}
    grouped: dict[str, dict[str, Mapping[str, Any]]] = {}
    for row in passes:
        if not row.get("error"):
            grouped.setdefault(str(row["item_id"]), {})[str(row["pass_name"])] = row
    return [
        verdict
        for item_id, slot in grouped.items()
        if item_id in items_by_id and (verdict := core.staged_verdict(items_by_id[item_id], slot))
    ]


def cmd_report(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    yard: dict[str, list[float]] = {}
    for path in sorted(run_dir.glob("scores_*.jsonl")):
        for row in _rows(path):
            if not row.get("error"):
                yard.setdefault(str(row["script_id"]), []).append(float(row["score"]))
    yard_mean = {key: sum(values) / len(values) for key, values in yard.items()}
    tables = [
        core.metrics(
            [
                core.Verdict(
                    "yardstick", key, key.rpartition("-")[0], key.rpartition("-")[2], value, {}
                )
                for key, value in yard_mean.items()
            ],
            yard_mean,
        )
    ]
    files = {
        "current_batch": "scored_current_batch_all.jsonl",
        "current_single": "scored_current_single.jsonl",
        "quoted": "scored_quoted.jsonl",
    }
    for scorer, filename in files.items():
        if verdicts := _verdicts(_rows(run_dir / filename), scorer):
            tables.append(core.metrics(verdicts, yard_mean))
    passes = _rows(run_dir / "passes_staged.jsonl")
    if staged := _staged_verdicts(run_dir, passes):
        tables.append(core.metrics(staged, yard_mean))
    text = core.render_report(tables, _pass_gaps(passes))
    (run_dir / "report.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="评审分趟对照实验（离线）")
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=str(copy_ab._default_db()), help="本机库（只读）")
    common.add_argument("--run", required=True, help="运行目录")

    def add(
        name: str, func: Callable[[argparse.Namespace], int], help_text: str
    ) -> argparse.ArgumentParser:
        child = sub.add_parser(name, help=help_text, parents=[common])
        child.set_defaults(func=func)
        return child

    build = add("build", cmd_build, "从 A/B 出稿里挑原稿，造对照稿")
    build.add_argument(
        "--ab-run", required=True, help="A/B 运行目录（含 scripts.jsonl 与尺子打分）"
    )
    build.add_argument("--per-sample", type=int, default=2, help="每个样本挑几篇原稿")

    yard = add("yard", cmd_yard, "尺子独立打分")
    yard.add_argument("--judge", required=True, help="引擎配置里当尺子的文本模型端点名")
    yard.add_argument("--judge-model", default="", help="换用该端点下的别的模型")
    yard.add_argument("--tag", default="", help="产物文件名后缀（多把尺子并存）")
    yard.add_argument("--repeats", type=int, default=2)
    yard.add_argument("--workers", type=int, default=4)

    score = add("score", cmd_score, "某个评审评一遍")
    score.add_argument("--scorer", required=True, choices=SCORERS)
    score.add_argument("--workers", type=int, default=4)

    add("report", cmd_report, "结论页")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
