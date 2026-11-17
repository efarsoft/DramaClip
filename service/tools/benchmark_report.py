"""对标剧量化差距报告 CLI（分析产物在库即测，零媒体重跑）。

逐项目统计六项节奏/密度指标，与行业抽样参考区间对账出差距表：
  集长编排 / 首句开口 / 台词跨度占比 / 语速字每秒 / 平均镜长 / 末句留白
（测的是**素材原剧形态**——我方成片质量另走成片自检链，两者别混读。）

数据源全部来自 dev 库现成产物：episodes.duration、episode_analysis 的
asr_segments / scene_data。台词跨度占比是 ASR 识别下界（识别不到的不计入）。
语速参考按题材分档（古装权谋语速天然慢于常规题材，genre 列在手）。

用法：
  uv run python tools/benchmark_report.py [--db ../data/data.db]

产出 markdown 报告（stdout）：每项目一节 + 全项目差距总表。参考区间是横向
参考不是质量门槛——形态差异（素材本身不是微短剧节奏）按「形态外」标注，
不判好差。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from pathlib import Path

# 行业抽样参考区间（横向参考，非质量门槛；古装权谋语速单独一档）
_REF_FIRST_EP_S = (90.0, 225.0)
_REF_REG_EP_S = (36.0, 63.0)
_REF_SHOT_S = (2.4, 3.1)
_REF_VOICED_RATIO = (0.65, 0.84)
_REF_WPS_NORMAL = (3.9, 5.8)
_REF_WPS_PERIOD = (2.3, 3.3)  # 古装权谋档（≈2.8 中值带 ±0.5 容差）
_REF_TAIL_SILENCE_MAX = 1.2

_GENRE_PERIOD_KEYS = ("古装", "权谋", "宫斗", "历史")


def _p50(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def _fmt(value: float, unit: str = "") -> str:
    return f"{value:.2f}{unit}" if value else "—"


def _in_range(value: float, lo: float, hi: float) -> bool:
    return lo <= value <= hi


def _episode_metrics(row: sqlite3.Row) -> dict[str, float | None]:
    """单集六项指标：缺产物（未分析/字段空）的项给 None 不参与汇总。"""
    duration = float(row["duration"] or 0.0)
    if duration <= 0:
        return {}
    asr = json.loads(row["asr_segments"] or "[]")
    scenes = json.loads(row["scene_data"] or "[]")
    spans = [
        (float(seg["start"]), float(seg["end"]), str(seg.get("text") or ""))
        for seg in asr
        if float(seg.get("end", 0)) > float(seg.get("start", 0))
    ]
    # 台词跨度（ASR 识别段的并集时长）是台词时长的**下界**：识别不到的台词不计入，
    # 占比偏低有识别偏薄的成分——报告里写明「识别下界」防止误读成素材问题。
    speech_s = sum(end - start for start, end, _ in spans)
    voiced_s = speech_s
    return {
        "duration": duration,
        "first_line_s": min((start for start, _, _ in spans), default=None),
        "voiced_ratio": min(voiced_s / duration, 1.0) if voiced_s else None,
        "wps": (
            sum(len(text) for _, _, text in spans) / speech_s if speech_s > 0 else None
        ),
        "shot_s": (
            statistics.fmean(
                b["end"] - b["start"]
                for b in scenes
                if float(b.get("end", 0)) > float(b.get("start", 0))
            )
            if scenes
            else None
        ),
        "tail_silence_s": (
            duration - max(end for _, end, _ in spans) if spans else None
        ),
    }


def _project_report(conn: sqlite3.Connection) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT p.name AS project, p.id AS pid, e.episode_number AS number,
               e.duration AS duration, ea.asr_segments AS asr_segments,
               ea.scene_data AS scene_data, ea.audio_features AS audio_features,
               ea.genre AS genre
        FROM projects p
        JOIN episodes e ON e.project_id = p.id
        LEFT JOIN episode_analysis ea ON ea.episode_id = e.id
        WHERE e.duration IS NOT NULL AND e.duration > 0
        ORDER BY p.name, e.episode_number
        """
    ).fetchall()
    projects: dict[str, dict[str, object]] = {}
    for row in rows:
        item = projects.setdefault(
            row["project"],
            {"episodes": [], "first_episode": None, "genre": row["genre"] or ""},
        )
        metrics = _episode_metrics(row)
        if not metrics:
            continue
        item["episodes"].append(metrics)  # type: ignore[union-attr]
        if row["number"] == 1:
            item["first_episode"] = metrics  # type: ignore[assignment]
    return [dict(name=name, **data) for name, data in projects.items()]


def _judgement(value: float, lo: float, hi: float) -> str:
    return "区间内" if _in_range(value, lo, hi) else (
        "偏低" if value < lo else "偏高"
    )


def render(projects: list[dict[str, object]]) -> str:
    lines: list[str] = ["# 对标剧量化差距报告（v1）", ""]
    lines.append(
        "> 参考区间为微短剧行业抽样横值，仅横向参考非质量门槛。本报告测的是"
        "**素材原剧形态**（非我方成片）；素材节奏与参考区间有差距=我方选段/剪辑"
        "有可操作空间，不等于素材差。"
    )
    lines.append("")
    for project in projects:
        eps: list[dict[str, float | None]] = project["episodes"]  # type: ignore[assignment]
        first: dict[str, float | None] | None = project["first_episode"]  # type: ignore[assignment]
        genre = str(project["genre"] or "")
        regular = eps[1:] if first else eps
        durations = [float(m["duration"]) for m in eps]
        first_dur = float(first["duration"]) if first else 0.0
        wps_ref = _REF_WPS_PERIOD if any(k in genre for k in _GENRE_PERIOD_KEYS) else _REF_WPS_NORMAL
        wps = _p50([float(m["wps"]) for m in eps if m.get("wps") is not None])
        voiced = _p50([float(m["voiced_ratio"]) for m in eps if m.get("voiced_ratio") is not None])
        shot = _p50([float(m["shot_s"]) for m in eps if m.get("shot_s") is not None])
        tail = _p50([float(m["tail_silence_s"]) for m in eps if m.get("tail_silence_s") is not None])
        first_line = _p50(
            [float(m["first_line_s"]) for m in eps if m.get("first_line_s") is not None]
        )
        lines.append(f"## {project['name']}")
        lines.append("")
        lines.append(
            f"- 集数 {len(eps)}，集长 min/p50/max = "
            f"{min(durations):.0f} / {_p50(durations):.0f} / {max(durations):.0f}s"
            + (f"，首集 {first_dur:.0f}s" if first_dur else "")
        )
        lines.append(f"- 首句开口 p50 {_fmt(first_line, 's')}，末句留白 p50 {_fmt(tail, 's')}")
        lines.append(
            f"- 台词跨度占比 p50 {_fmt(voiced * 100, '%')}（识别下界），"
            f"语速 p50 {_fmt(wps, '字/s')}（题材：{genre or '未标注'}），"
            f"平均镜长 p50 {_fmt(shot, 's')}"
        )
        lines.append("")
        if not regular:
            continue
        reg_dur = _p50([float(m["duration"]) for m in regular])
        lines.append("| 维度 | 参考区间 | 本项目实测 | 判定 |")
        lines.append("| --- | --- | --- | --- |")
        first_ref = (
            "区间内"
            if _in_range(first_dur, *_REF_FIRST_EP_S)
            else ("偏低" if first_dur < _REF_FIRST_EP_S[0] else "偏高")
        )
        lines.append(
            f"| 首集时长 | {_REF_FIRST_EP_S[0]:.0f}–{_REF_FIRST_EP_S[1]:.0f}s "
            f"| {_fmt(first_dur, 's')} | {first_ref} |"
        )
        lines.append(
            f"| 常规集时长 | {_REF_REG_EP_S[0]:.0f}–{_REF_REG_EP_S[1]:.0f}s "
            f"| {_fmt(reg_dur, 's')} | {_judgement(reg_dur, *_REF_REG_EP_S)} |"
        )
        lines.append(
            f"| 平均镜长 | {_REF_SHOT_S[0]}–{_REF_SHOT_S[1]}s "
            f"| {_fmt(shot, 's')} | {_judgement(shot, *_REF_SHOT_S)} |"
        )
        lines.append(
            f"| 台词跨度占比（识别下界） | {_REF_VOICED_RATIO[0]*100:.0f}–{_REF_VOICED_RATIO[1]*100:.0f}% "
            f"| {_fmt(voiced * 100, '%')} "
            f"| {_judgement(voiced, *_REF_VOICED_RATIO)} |"
        )
        lines.append(
            f"| 语速 | {wps_ref[0]}–{wps_ref[1]}字/s | {_fmt(wps, '字/s')} "
            f"| {_judgement(wps, *wps_ref)} |"
        )
        lines.append(
            f"| 末句留白 | ≤{_REF_TAIL_SILENCE_MAX}s | {_fmt(tail, 's')} "
            f"| {'区间内' if tail <= _REF_TAIL_SILENCE_MAX else '留白偏长'} |"
        )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="../data/data.db", help="dev 库路径")
    args = parser.parse_args()
    conn = sqlite3.connect(f"file:{Path(args.db).resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        print(render(_project_report(conn)))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
