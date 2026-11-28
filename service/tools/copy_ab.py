"""文案规则 A/B 的读写半边：冻结样本、出稿、复述、裁判（两两盲评 / 独立打分）、出结论页。

为什么这么设计：
- 出稿走生产的剧本链入口（script_driver.script_dialogue_plan），B 版只经 settings 的
  提示词覆盖键喂进去——与用户在设置页改提示词是同一条路，生产代码零改动。
- 裁判与写作必须是两个模型：作者给自己的稿子打分有系统性偏袒，换家族才当得起「盲评」。
- 裁判钥匙只由本机库直读进内存，不落盘不打印；产物都在运行目录（data/ 不进仓库），
  素材转写与成稿不外发。
- 每一步都能接着跑：已成稿/已评的条目重跑时跳过，裁判连续无效到上限就熔断。

配对、判决聚合、判定线与结论页在 tools/copy_ab_core.py；独立打分协议与裁判校准统计在
tools/copy_ab_score.py（都是纯函数，可单测）。

子命令（运行目录默认建在本机库旁边：data/ab/<时间戳>/）：
  samples      [--run DIR] [--window ID=剧名:1-3 …]     从本机库冻结固定样本（每样本一条取材角度）
  generate     --run DIR [--candidates N] [--limit N]    每样本每版出 N 篇（生产入口 + 生产审查闸）
  retell       --run DIR                                 每篇稿过一遍生产的复述测试（回归用）
  judge        --run DIR --judge 配置名 [--kinds …] [--tag 名] [--judge-model 模型]  两两盲评
  report       --run DIR                                 四条判定线对数字 → 结论与引文
  score        --run DIR --judge 配置名 [--judge-model 模型] [--tag 名]               独立打分
  score-report --run DIR                                 裁判校准页：稳不稳、有没有共识、位置偏不偏
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dramaclip.api.context import AppContext  # noqa: E402
from dramaclip.engines.narration import angles, script_driver, styles  # noqa: E402
from dramaclip.engines.narration.pipeline import MODE_LABELS  # noqa: E402
from dramaclip.engines.narration.retell import retell_check  # noqa: E402
from dramaclip.engines.semantic.llm_client import (  # noqa: E402
    LlmClient,
    LlmUnavailable,
    client_for,
    redact_secrets,
)
from dramaclip.flows.narration import _collect_episode_inputs, _speaker_mapping_of  # noqa: E402
from dramaclip.infra.storage.repos import analysis as analysis_repo  # noqa: E402
from dramaclip.infra.storage.repos import engine_configs as configs_repo  # noqa: E402
from tools import copy_ab_score as scoring  # noqa: E402
from tools.copy_ab_core import (  # noqa: E402
    FUNDAMENTALS_KEY,
    JUDGE_STRIKE_MAX,
    JUDGE_SYSTEM,
    JUDGE_TIMEOUT_S,
    JUDGE_USER,
    MODE,
    VARIANTS,
    Judgment,
    Present,
    Sample,
    Script,
    build_pairs,
    build_presents,
    evaluate,
    parse_judgment,
    quote_found,
    render_report,
    variant_settings,
)

# dev 库两部已分析的微短剧，各切三段：一都市家庭、一古装，前中后段各占一席。
DEV_WINDOWS: tuple[tuple[str, str, str], ...] = (
    ("dujia_open", "钟情错付再回首", "1-3"),
    ("dujia_mid", "钟情错付再回首", "4-6"),
    ("dujia_late", "钟情错付再回首", "7-10"),
    ("guzhuang_open", "海狱归来，我以龙魂镇山河", "1-3"),
    ("guzhuang_mid", "海狱归来，我以龙魂镇山河", "4-6"),
    ("guzhuang_late", "海狱归来，我以龙魂镇山河", "7-10"),
)


# ---------------------------------------------------------------------------
# 本机库读取（只读；密钥只在内存里走一遭，不落盘不打印）
# ---------------------------------------------------------------------------


def _default_db() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "data.db"


def _connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _load_settings(conn: sqlite3.Connection) -> dict[str, str]:
    return {str(key): str(value) for key, value in conn.execute("SELECT key, value FROM settings")}


@dataclass(frozen=True)
class _ConnOnly:
    """生产 `_collect_episode_inputs` 的连接替身：那个函数只读 context.conn。"""

    conn: sqlite3.Connection


def _episode_inputs(
    conn: sqlite3.Connection, episode_ids: Sequence[str], settings: Mapping[str, str]
) -> list[dict[str, Any]]:
    """与生产同一份装配：转写解析、真名映射、镜头切点、画面轨都在这里落定。"""
    placeholders = ",".join("?" * len(episode_ids))
    rows = conn.execute(
        "SELECT id, episode_number, duration, project_id FROM episodes "
        f"WHERE id IN ({placeholders}) ORDER BY episode_number",
        tuple(episode_ids),
    ).fetchall()
    inputs = _collect_episode_inputs(
        cast(AppContext, _ConnOnly(conn)),
        [dict(row) for row in rows],
        _speaker_mapping_of(settings),
    )
    return list(inputs)


def _host(base_url: str) -> str:
    try:
        return urlsplit(base_url).netloc
    except ValueError:
        return base_url


def _judge_settings(
    conn: sqlite3.Connection, name: str, writer: Mapping[str, str], model_override: str = ""
) -> dict[str, str]:
    """按配置名取裁判端点：钥匙从库里直读进内存；与写作是同一端点同一模型就拒绝。"""
    configs = configs_repo.list_by_domain(conn, "llm")
    matches = [config for config in configs if str(config["name"]).strip() == name]
    if not matches:
        names = "、".join(str(config["name"]) for config in configs) or "无"
        raise SystemExit(f"引擎配置里没有名为「{name}」的文本模型端点（现有：{names}）")
    config = matches[0]
    out = {
        "llm.base_url": str(config["base_url"]),
        "llm.api_key": configs_repo.get_secret(conn, str(config["id"])),
        "llm.model": model_override.strip() or str(config["model"]),
        "llm.timeout_s": str(JUDGE_TIMEOUT_S),
    }
    if not out["llm.api_key"]:
        raise SystemExit(f"配置「{name}」没有存钥匙，请先在引擎页补上")
    same = (out["llm.model"], _host(out["llm.base_url"])) == (
        writer.get("llm.model", ""),
        _host(writer.get("llm.base_url", "")),
    )
    if same:
        raise SystemExit("裁判与写作是同一端点的同一模型，盲评不成立")
    return out


def _judge_endpoint(args: argparse.Namespace) -> tuple[dict[str, str], str]:
    conn = _connect(Path(args.db))
    judge_settings = _judge_settings(conn, args.judge, _load_settings(conn), args.judge_model)
    conn.close()
    return judge_settings, judge_settings["llm.model"]


# ---------------------------------------------------------------------------
# 运行目录读写
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _append_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_meta(run_dir: Path, **fields: Any) -> None:
    path = run_dir / "meta.json"
    meta: dict[str, Any] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    meta.update(fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


def _load_samples(run_dir: Path) -> list[Sample]:
    path = run_dir / "samples.json"
    if not path.is_file():
        raise SystemExit(f"{path} 不存在：先跑 samples 冻结样本")
    rows: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return [
        Sample(
            **{
                key: (tuple(value) if isinstance(value, list) else value)
                for key, value in row.items()
            }
        )
        for row in rows
    ]


def _load_scripts(run_dir: Path) -> list[Script]:
    seen: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(run_dir / "scripts.jsonl"):
        seen[str(row["script_id"])] = row  # 同一篇重出过以最后一次为准
    return [
        Script(
            str(row["script_id"]),
            str(row["sample_id"]),
            str(row["variant"]),
            int(row["index"]),
            bool(row["ok"]),
            tuple(str(text) for text in row["texts"]),
            int(row["dropped"]),
            str(row["error"]),
        )
        for row in seen.values()
    ]


def _load_judgments(run_dir: Path, name: str = "judgments.jsonl") -> list[Judgment]:
    """同一呈现评过多次时取最后一条有效的（重跑会接着评，不重复计）。"""
    seen: dict[tuple[str, int], Judgment] = {}
    for row in _read_jsonl(run_dir / name):
        judgment = Judgment(
            str(row["pair_id"]),
            int(row["order_no"]),
            str(row["first_id"]),
            str(row["picked_id"]),
            bool(row["quote_ok"]),
            str(row["reason"]),
            str(row["quote_first"]),
            str(row["quote_second"]),
            str(row["error"]),
        )
        key = (judgment.pair_id, judgment.order_no)
        if not judgment.error or key not in seen:  # 有效的优先：后来的失败不盖掉已评成的
            seen[key] = judgment
    return list(seen.values())


def _load_retells(run_dir: Path) -> dict[str, dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(run_dir / "retell.jsonl"):
        if not row.get("error") or str(row["script_id"]) not in seen:
            seen[str(row["script_id"])] = row
    return seen


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------


def _parse_span(span: str) -> tuple[int, ...]:
    match = re.fullmatch(r"(\d+)(?:-(\d+))?", span.strip())
    if match is None:
        raise SystemExit(f"集区间写法不对：{span}（应为 1-3 或 7）")
    start, end = int(match.group(1)), int(match.group(2) or match.group(1))
    if end < start:
        raise SystemExit(f"集区间首尾颠倒：{span}")
    return tuple(range(start, end + 1))


def _parse_window(spec: str) -> tuple[str, str, str]:
    sample_id, _, rest = spec.partition("=")
    project_name, _, span = rest.rpartition(":")
    if not (sample_id.strip() and project_name.strip() and span.strip()):
        raise SystemExit(f"窗口写法不对：{spec}（应为 ID=剧名:1-3）")
    return sample_id.strip(), project_name.strip(), span.strip()


def _freeze_sample(
    conn: sqlite3.Connection,
    settings: Mapping[str, str],
    sample_id: str,
    project_name: str,
    span: str,
    trace_dir: Path,
) -> Sample:
    """一段集 + 一条生产选题角度冻结成一个样本：A/B 两版从此吃同一份原料。"""
    project = conn.execute("SELECT id FROM projects WHERE name = ?", (project_name,)).fetchone()
    if project is None:
        raise SystemExit(f"库里没有项目「{project_name}」")
    numbers = _parse_span(span)
    rows = conn.execute(
        "SELECT id, episode_number FROM episodes "
        f"WHERE project_id = ? AND episode_number IN ({','.join('?' * len(numbers))}) "
        "ORDER BY episode_number",
        (project["id"], *numbers),
    ).fetchall()
    missing = sorted(set(numbers) - {int(row["episode_number"]) for row in rows})
    if missing:
        raise SystemExit(f"「{project_name}」缺第 {missing} 集")
    episode_ids = [str(row["id"]) for row in rows]
    inputs = _episode_inputs(conn, episode_ids, settings)
    if not inputs:
        raise SystemExit(f"「{project_name}」第 {numbers} 集没有可用转写")
    record = analysis_repo.get(conn, episode_ids[0])
    genre = str(record["genre"]) if record is not None and record["genre"] else ""
    brief = angles.select_angles(
        MODE,
        mode_label=MODE_LABELS[MODE],
        k=1,
        episode_inputs=inputs,
        settings={**settings, "_project_name": project_name},
        excluded=[],
        trace_dir=trace_dir,
    )[0]
    return Sample(
        sample_id=sample_id,
        project_name=project_name,
        genre=genre,
        episode_ids=tuple(episode_ids),
        episode_numbers=tuple(int(row["episode_number"]) for row in rows),
        angle_name=brief.name,
        angle_block=angles.prompt_block(
            brief, include_style=not styles.is_manual_style(settings), mode=MODE
        ),
        wanted=tuple(brief.episode_numbers),
    )


def cmd_samples(args: argparse.Namespace) -> int:
    db = Path(args.db)
    run_dir = (
        Path(args.run) if args.run else db.resolve().parent / "ab" / time.strftime("%Y%m%d_%H%M%S")
    )
    out_path = run_dir / "samples.json"
    if out_path.is_file() and not args.force:
        raise SystemExit(f"{out_path} 已有样本；要重新冻结请加 --force")
    conn = _connect(db)
    settings = _load_settings(conn)
    windows = [_parse_window(spec) for spec in args.window] if args.window else DEV_WINDOWS
    samples: list[Sample] = []
    for sample_id, project_name, span in windows:
        try:
            samples.append(
                _freeze_sample(conn, settings, sample_id, project_name, span, run_dir / "traces")
            )
        except (ValueError, LlmUnavailable) as exc:
            raise SystemExit(
                f"冻结样本 {sample_id} 失败：{redact_secrets(str(exc))[:200]}"
            ) from exc
    run_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps([asdict(sample) for sample in samples], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    _write_meta(run_dir, run_id=run_dir.name, writer=settings.get("llm.model", ""))
    print(f"已冻结 {len(samples)} 个样本 → {out_path}")
    for sample in samples:
        span = f"第 {sample.episode_numbers[0]}–{sample.episode_numbers[-1]} 集"
        print(f"- {sample.sample_id}：{sample.project_name} {span}；角度「{sample.angle_name}」")
    return 0


def _write_one(
    conn: sqlite3.Connection,
    base: Mapping[str, str],
    sample: Sample,
    variant: str,
    index: int,
    trace_dir: Path,
) -> Script:
    """出一篇稿：生产入口、生产审查闸（带规则原句重掷）全照旧；失败本身也是结果。"""
    script_id = f"{sample.sample_id}-{variant}{index}"
    try:
        wanted = set(sample.wanted)
        scoped = [
            episode
            for episode in _episode_inputs(conn, sample.episode_ids, base)
            if int(episode["number"]) in wanted
        ]
        if not scoped:
            raise ValueError("角度块取材的集都没有转写")
        plan, _used = script_driver.script_dialogue_plan(
            scoped,
            variant_settings(base, sample, variant),
            angle_block=sample.angle_block,
            trace_dir=trace_dir,
        )
        texts = tuple(str(item.text) for item in plan.narration_texts if str(item.text).strip())
        if not texts:
            raise ValueError("方案没有旁白")
        return Script(
            script_id,
            sample.sample_id,
            variant,
            index,
            True,
            texts,
            len(plan.dropped_segments or []),
            "",
        )
    except Exception as exc:  # noqa: BLE001 - 这一篇出不了是对照实验的一格数据，不是工具故障
        error = redact_secrets(f"{type(exc).__name__}: {exc}")[:300]
        return Script(script_id, sample.sample_id, variant, index, False, (), 0, error)


def cmd_generate(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    samples = _load_samples(run_dir)
    if args.limit:
        samples = samples[: args.limit]
    conn = _connect(Path(args.db))
    base = _load_settings(conn)
    if base.get(FUNDAMENTALS_KEY):
        raise SystemExit("本机设置里已有「解说基本功」提示词覆盖：A 版不再是生产默认，对照不成立")
    done = {
        str(row["script_id"]) for row in _read_jsonl(run_dir / "scripts.jsonl") if row.get("ok")
    }
    for sample in samples:
        for variant in [v.strip() for v in getattr(args, "variants", "").split(",") if v.strip()] or list(VARIANTS):
            for index in range(1, args.candidates + 1):
                script_id = f"{sample.sample_id}-{variant}{index}"
                if script_id in done:
                    print(f"{script_id}：已有，跳过")
                    continue
                started = time.monotonic()
                script = _write_one(conn, base, sample, variant, index, run_dir / "traces")
                _append_jsonl(run_dir / "scripts.jsonl", [asdict(script)])
                spent = time.monotonic() - started
                if script.ok:
                    print(
                        f"{script_id}：成稿 {script.chars} 字 / {len(script.texts)} 段，{spent:.0f}s",
                        flush=True,
                    )
                else:
                    print(f"{script_id}：失败（{spent:.0f}s）— {script.error}", flush=True)
    return 0


def cmd_retell(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    conn = _connect(Path(args.db))
    client = client_for(_load_settings(conn), site="复述测试")
    done = {
        str(row["script_id"])
        for row in _read_jsonl(run_dir / "retell.jsonl")
        if not row.get("error")
    }
    for script in _load_scripts(run_dir):
        if not script.ok or script.script_id in done:
            continue
        row: dict[str, Any] = {"script_id": script.script_id, "variant": script.variant}
        try:
            report = retell_check(script.text, client)
            row.update(
                passed=report.passed,
                confusions=len(report.confusions),
                reasons=list(report.reasons),
                error="",
            )
            outcome = "通过" if report.passed else "未过"
            print(f"{script.script_id}：{outcome}，卡点 {len(report.confusions)}", flush=True)
        except Exception as exc:  # noqa: BLE001 - 调用失败是未知，记下原因，重跑会再试
            row.update(
                passed=False,
                confusions=0,
                reasons=[],
                error=redact_secrets(f"{type(exc).__name__}: {exc}")[:300],
            )
            print(f"{script.script_id}：复述调用失败 — {row['error']}", flush=True)
        _append_jsonl(run_dir / "retell.jsonl", [row])
    return 0


def judge_present(client: LlmClient, present: Present, text_of: Mapping[str, str]) -> Judgment:
    """评一次呈现：输出不合约定换温度再试一次，仍不合就记无效。"""
    first_text, second_text = text_of[present.first_id], text_of[present.second_id]
    user = JUDGE_USER.format(first=first_text, second=second_text)
    error = ""
    for temperature in (0.0, 0.3):
        try:
            parsed = parse_judgment(client.chat_json(JUDGE_SYSTEM, user, temperature=temperature))
        except Exception as exc:  # noqa: BLE001 - 记成无效判决；连续无效由调用方熔断
            error = redact_secrets(f"{type(exc).__name__}: {exc}")[:300]
            continue
        if parsed is None:
            error = "裁判输出不合约定"
            continue
        prefer, quote_first, quote_second, reason = parsed
        return Judgment(
            present.pair_id,
            present.order_no,
            present.first_id,
            {"甲": present.first_id, "乙": present.second_id}.get(prefer, ""),
            quote_found(quote_first, first_text) and quote_found(quote_second, second_text),
            reason,
            quote_first,
            quote_second,
            "",
        )
    return Judgment(
        present.pair_id, present.order_no, present.first_id, "", False, "", "", "", error
    )


class _JudgeDown(Exception):
    """裁判端点建不起客户端：整次调用记无效，由并发器按连续无效熔断。"""


@dataclass
class _Progress:
    done: int = 0
    streak: int = 0  # 连续无效的判决数：到上限就熔断
    stop: bool = False


def _run_parallel[Item, Result](
    judge_settings: Mapping[str, str],
    pending: Sequence[Item],
    out_path: Path,
    workers: int,
    work: Callable[[Item, LlmClient], Result],
    label_of: Callable[[Result], str],
) -> int:
    """多路并发把 pending 逐个做完：每路各建一个客户端；落盘串行加锁，连续无效到上限就熔断。"""
    lock = threading.Lock()
    progress = _Progress()

    def run(item: Item) -> Result:
        try:
            client = client_for(judge_settings, min_timeout_s=JUDGE_TIMEOUT_S, site="盲评裁判")
        except LlmUnavailable as exc:
            raise _JudgeDown(redact_secrets(str(exc))[:300]) from exc
        return work(item, client)

    def settle(outcome: Result | _JudgeDown) -> None:
        with lock:
            progress.done += 1
            error = (
                str(outcome)
                if isinstance(outcome, _JudgeDown)
                else str(getattr(outcome, "error", ""))
            )
            row: dict[str, Any] = (
                {"error": error} if isinstance(outcome, _JudgeDown) else asdict(outcome)
            )
            _append_jsonl(out_path, [row])
            progress.streak = progress.streak + 1 if error else 0
            label = (
                f"裁判端点不可用：{error}" if isinstance(outcome, _JudgeDown) else label_of(outcome)
            )
            print(f"[{progress.done}/{len(pending)}] {label}", flush=True)
            if progress.streak >= JUDGE_STRIKE_MAX:
                progress.stop = True

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(run, item) for item in pending]
        for future in as_completed(futures):
            try:
                outcome: Result | _JudgeDown = future.result()
            except _JudgeDown as exc:
                outcome = exc
            settle(outcome)
            if progress.stop:
                for rest in futures:
                    rest.cancel()
    if progress.stop:
        raise SystemExit(
            f"连续 {JUDGE_STRIKE_MAX} 次判决无效（多为额度或网络），先停；修好后重跑会接着评"
        )
    return 0


def cmd_judge(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    judge_settings, model = _judge_endpoint(args)
    tag = args.tag.strip()
    client = client_for(judge_settings, min_timeout_s=JUDGE_TIMEOUT_S, site="盲评裁判")
    print(f"裁判 {model} 连通，往返 {client.ping():.1f}s", flush=True)
    _write_meta(run_dir, **{f"judge_{tag}" if tag else "judge": model})
    scripts = _load_scripts(run_dir)
    kinds = tuple(kind.strip() for kind in args.kinds.split(",") if kind.strip())
    presents = [
        present
        for present in build_presents(build_pairs(scripts), args.seed)
        if present.kind in kinds
    ]
    text_of = {script.script_id: script.text for script in scripts}
    out_name = f"judgments_{tag}.jsonl" if tag else "judgments.jsonl"
    done = {
        (str(row["pair_id"]), int(row["order_no"]))
        for row in _read_jsonl(run_dir / out_name)
        if not row.get("error")
    }
    pending = [present for present in presents if (present.pair_id, present.order_no) not in done]
    print(
        f"成稿 {len(scripts)} 篇，配对类型 {'/'.join(kinds)}，共 {len(presents)} 次呈现，"
        f"待评 {len(pending)}（{args.workers} 路并发）",
        flush=True,
    )

    def work(present: Present, client: LlmClient) -> Judgment:
        return judge_present(client, present, text_of)

    def label_of(judgment: Judgment) -> str:
        verdict = f"无效：{judgment.error}" if judgment.error else (judgment.picked_id or "差不多")
        return f"{judgment.pair_id} 第 {judgment.order_no} 次 → {verdict}"

    return _run_parallel(judge_settings, pending, run_dir / out_name, args.workers, work, label_of)


def cmd_report(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    scripts = _load_scripts(run_dir)
    report = evaluate(
        scripts, build_pairs(scripts), _load_judgments(run_dir), _load_retells(run_dir)
    )
    meta: dict[str, Any] = {"samples": len({script.sample_id for script in scripts})}
    meta_path = run_dir / "meta.json"
    if meta_path.is_file():
        meta.update(json.loads(meta_path.read_text(encoding="utf-8")))
    text = render_report(report, meta)
    (run_dir / "report.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    judge_settings, model = _judge_endpoint(args)
    judge = args.tag.strip() or model
    scripts = [script for script in _load_scripts(run_dir) if script.ok]
    out_path = run_dir / f"scores_{judge}.jsonl"
    done = {
        (str(row["script_id"]), int(row["repeat"]))
        for row in _read_jsonl(out_path)
        if not row.get("error")
    }
    pending = scoring.pending_scores(scripts, args.repeats, done)
    print(
        f"裁判 {judge}（{model}）：{len(scripts)} 篇 × {args.repeats} 次，"
        f"待打 {len(pending)}（{args.workers} 路并发）",
        flush=True,
    )
    return _run_parallel(
        judge_settings,
        pending,
        out_path,
        args.workers,
        scoring.score_work(judge),
        scoring.score_label,
    )


def cmd_score_report(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    scripts = _load_scripts(run_dir)
    rows = [row for path in sorted(run_dir.glob("scores_*.jsonl")) for row in _read_jsonl(path)]
    judges = sorted({str(row["judge"]) for row in rows})
    stats = [stat for judge in judges if (stat := scoring.judge_stats(rows, judge, scripts))]
    agreement = {
        (judge_a, judge_b): scoring.judges_agreement(rows, judge_a, judge_b)
        for index, judge_a in enumerate(judges)
        for judge_b in judges[index + 1 :]
    }
    meta: dict[str, Any] = (
        json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        if (run_dir / "meta.json").is_file()
        else {}
    )
    positions = {
        str(
            meta.get(f"judge_{path.stem.removeprefix('judgments_')}", path.stem)
        ): scoring.position_stats(_read_jsonl(path))
        for path in sorted(run_dir.glob("judgments_*.jsonl"))
    }
    text = scoring.render_score_report(stats, agreement, positions)
    (run_dir / "score_report.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="文案规则 A/B：出稿 → 盲评 → 判定线")
    sub = parser.add_subparsers(dest="cmd", required=True)
    default_db = str(_default_db())

    def add_db(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--db", default=default_db, help="本机库路径（只读）")

    ps = sub.add_parser("samples", help="从本机库冻结固定样本")
    add_db(ps)
    ps.add_argument("--run", default="", help="运行目录（不填则建在本机库旁边 ab/<时间戳>）")
    ps.add_argument(
        "--window",
        action="append",
        help="ID=剧名:集区间，如 dujia_open=钟情错付再回首:1-3；不填用 dev 预设六段",
    )
    ps.add_argument("--force", action="store_true", help="覆盖运行目录里已有的 samples.json")
    ps.set_defaults(func=cmd_samples)

    pg = sub.add_parser("generate", help="每样本每版出 N 篇（生产入口 + 生产审查闸）")
    add_db(pg)
    pg.add_argument("--run", required=True, help="运行目录")
    pg.add_argument("--candidates", type=int, default=3, help="每样本每版几篇（默认 3）")
    pg.add_argument("--limit", type=int, default=0, help="只跑前 N 个样本（试点用）")
    pg.add_argument(
        "--variants", default="", help="只跑这些版（逗号分隔，如 C）；缺省=A,B 两臂全跑"
    )
    pg.set_defaults(func=cmd_generate)

    pr = sub.add_parser("retell", help="每篇稿过一遍生产的复述测试")
    add_db(pr)
    pr.add_argument("--run", required=True, help="运行目录")
    pr.set_defaults(func=cmd_retell)

    pj = sub.add_parser("judge", help="裁判两两盲评")
    add_db(pj)
    pj.add_argument("--run", required=True, help="运行目录")
    pj.add_argument("--judge", required=True, help="裁判端点的配置名（引擎页里的名称）")
    pj.add_argument("--judge-model", default="", help="换用同一端点上的另一个模型")
    pj.add_argument("--kinds", default="ab,aa,bb", help="配对类型：ab=跨版对照，aa/bb=同版对照")
    pj.add_argument("--tag", default="", help="结果另存为 judgments_<名>.jsonl（多裁判并存时用）")
    pj.add_argument("--seed", type=int, default=20261125, help="首次呈现谁标甲的随机种子")
    pj.add_argument("--workers", type=int, default=4, help="并发路数（默认 4）")
    pj.set_defaults(func=cmd_judge)

    po = sub.add_parser("report", help="四条判定线对数字 → 结论与引文")
    po.add_argument("--run", required=True, help="运行目录")
    po.set_defaults(func=cmd_report)

    scoring.register_commands(sub, add_db, cmd_score, cmd_score_report)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
