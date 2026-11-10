"""harness 只读聚合（specs/2026-10-23-data-feedback-harness.md §2/§4/§5）。

中位数抗爆款绑架；plays=0 剔除；辅指标缺失条目不补 0；离群 >2σ 点名不进中位。
健康线/差异阈值是通用基准初始值，标注待回流自建校准；建议只输出文案，不自动调权
（自进化第三层明确不做）。
"""

from __future__ import annotations

import statistics
from datetime import date
from typing import Any

DIMENSIONS = ("mode", "arc", "angle", "platform", "duration_bucket")

HEALTH_3S = 32.0
HEALTH_RETENTION = 30.0
HEALTH_NOTE = "通用基准初始值，回流数据足够后自建校准"


def duration_bucket(duration_s: float | None) -> str:
    if duration_s is None:
        return "未知"
    if duration_s < 30:
        return "<30s"
    if duration_s < 60:
        return "30-60s"
    if duration_s < 90:
        return "60-90s"
    return "90s+"


def _key(row: dict[str, Any], dimension: str) -> str:
    if dimension == "duration_bucket":
        return duration_bucket(row.get("duration_s"))
    if dimension == "platform":
        return str(row["platform"])
    return str(row.get(dimension) or "不可考")


def _median_rate(rows: list[dict[str, Any]], field: str) -> float | None:
    ratios = [float(r[field]) / r["plays"] for r in rows if r.get(field) is not None]
    return round(statistics.median(ratios), 4) if ratios else None


def aggregate(entries: list[dict[str, Any]], dimension: str) -> dict[str, Any]:
    if dimension not in DIMENSIONS:
        raise ValueError(f"dimension 必须是 {'/'.join(DIMENSIONS)} 之一")
    valid = [r for r in entries if r["plays"] > 0]
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in valid:
        groups.setdefault(_key(row, dimension), []).append(row)
    rows: list[dict[str, Any]] = []
    for value, members in groups.items():
        rets = [float(r["retention_pct"]) for r in members]
        mean = statistics.mean(rets)
        sigma = statistics.pstdev(rets)
        outliers = [
            r for r in members
            if sigma > 0 and abs(float(r["retention_pct"]) - mean) > 2 * sigma
        ]
        kept = [r for r in members if r not in outliers]
        n = len(members)
        rows.append({
            "value": value,
            "n": n,
            "median_retention_pct": (
                round(statistics.median([float(r["retention_pct"]) for r in kept]), 2)
                if kept else None
            ),
            "like_rate": _median_rate(members, "likes"),
            "share_rate": _median_rate(members, "shares"),
            "signal": "gray" if n < 10 else "yellow" if n < 30 else "ok",
            "outliers": [str(r["export_id"]) for r in outliers],
        })
    rows.sort(key=lambda r: (
        r["median_retention_pct"] is None, -(r["median_retention_pct"] or 0.0), r["value"]
    ))
    return {
        "dimension": dimension,
        "rows": rows,
        "recorded": len(entries),
        "zero_plays_excluded": len(entries) - len(valid),
    }


def health(entries: list[dict[str, Any]]) -> dict[str, Any]:
    below: list[dict[str, Any]] = []
    for row in entries:
        if row["plays"] <= 0:
            continue
        r3 = row.get("retention_3s")
        if r3 is not None and float(r3) < HEALTH_3S:
            below.append({
                "export_id": str(row["export_id"]),
                "project_name": str(row["project_name"]),
                "metric": "retention_3s",
                "value": float(r3),
                "suggestion": "钩子重选：前3秒留存低于基准，开场钩子没留住人",
            })
        if float(row["retention_pct"]) < HEALTH_RETENTION:
            below.append({
                "export_id": str(row["export_id"]),
                "project_name": str(row["project_name"]),
                "metric": "retention_pct",
                "value": float(row["retention_pct"]),
                "suggestion": "时长分析：完播低于基准，可切到时长分桶维度对照",
            })
    return {
        "line_3s": HEALTH_3S,
        "line_retention": HEALTH_RETENTION,
        "note": HEALTH_NOTE,
        "below": below,
    }


AB_WINDOW_DAYS = 3  # published_at 只录到日：72h 按 3 天计
AB_MIN_PLAYS = 500
AB_DIFF_PP = 5.0  # 初始值，回流数据足够后校准（P-R4）


def ab_pairs(entries: list[dict[str, Any]], *, now_ms: int) -> dict[str, Any]:
    """同项目同平台对照组（批二#6）：四态保守读数，方向性≠统计显著。"""
    dated: list[tuple[dict[str, Any], date]] = []
    for row in entries:
        raw = row.get("published_at")
        try:
            parsed = date.fromisoformat(str(raw)) if raw else None
        except ValueError:
            parsed = None
        if parsed is not None:
            dated.append((row, parsed))
    groups: dict[tuple[str, str], list[tuple[dict[str, Any], date]]] = {}
    for row, day in dated:
        groups.setdefault((str(row["project_id"]), str(row["platform"])), []).append((row, day))
    today = date.fromtimestamp(now_ms / 1000)
    pairs: list[dict[str, Any]] = []
    unpaired = len(entries) - len(dated)
    for (project_id, platform), members in sorted(groups.items()):
        members.sort(key=lambda m: (m[1], str(m[0]["export_id"])))
        matched: set[int] = set()
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                ri, di = members[i]
                rj, dj = members[j]
                if abs((di - dj).days) > AB_WINDOW_DAYS:
                    continue
                matched.add(i)
                matched.add(j)
                delta = round(float(ri["retention_pct"]) - float(rj["retention_pct"]), 2)
                if (today - di).days < AB_WINDOW_DAYS or (today - dj).days < AB_WINDOW_DAYS:
                    state, leader, note = "等待", None, "发布未满72h，数据仍在累积"
                elif ri["plays"] < AB_MIN_PLAYS or rj["plays"] < AB_MIN_PLAYS:
                    state, leader, note = "证据不足", None, "播放量不足500，样本未达门槛"
                elif abs(delta) < AB_DIFF_PP:
                    state, leader, note = (
                        "差异不明显", None, "完播差不足5个百分点（初始阈值，待校准）"
                    )
                else:
                    state = "方向性领先"
                    leader = str(ri["export_id"] if delta > 0 else rj["export_id"])
                    note = "方向性读数，非统计显著；建议复跑验证"
                pairs.append({
                    "project_id": project_id,
                    "project_name": str(ri["project_name"]),
                    "platform": platform,
                    "a": str(ri["export_id"]),
                    "b": str(rj["export_id"]),
                    "retention_a": float(ri["retention_pct"]),
                    "retention_b": float(rj["retention_pct"]),
                    "delta_pp": delta,
                    "state": state,
                    "leader": leader,
                    "note": note,
                })
        unpaired += len(members) - len(matched)
    return {
        "pairs": pairs,
        "unpaired": unpaired,
        "window_days": AB_WINDOW_DAYS,
        "min_plays": AB_MIN_PLAYS,
        "diff_pp": AB_DIFF_PP,
    }
