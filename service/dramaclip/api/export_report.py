"""harness 只读聚合（specs/2026-10-23-data-feedback-harness.md §2/§4/§5）。

中位数抗爆款绑架；plays=0 剔除；辅指标缺失条目不补 0；离群 >2σ 点名不进中位。
健康线/差异阈值是通用基准初始值，标注待回流自建校准；建议只输出文案，不自动调权
（自进化第三层明确不做）。
"""

from __future__ import annotations

import statistics
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
