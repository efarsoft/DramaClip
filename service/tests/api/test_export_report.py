"""harness 聚合（批二#7/#8/#9）：中位数/信号纪律/离群点名/健康线——纯函数钉死。

变异锚点：均值换中位数即红（偏态集）；灰黄边界 n=9/10/29/30 四点钉；
plays=0 剔除、缺失辅指标不补 0、方案断链标不可考，各有专杀用例。
"""

from __future__ import annotations

from typing import Any

import pytest

from dramaclip.api import export_report


def _entry(export_id: str, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "export_id": export_id, "project_id": "p1", "project_name": "剧一",
        "mode": "full_narration", "angle": "逆袭", "arc": "triumph",
        "duration_s": 60.0, "platform": "抖音", "plays": 1000,
        "retention_pct": 30.0, "likes": None, "shares": None,
        "retention_3s": None, "published_at": None, "video_id": None,
    }
    return {**base, **over}


def test_median_not_mean() -> None:
    # n=5 时单点 z 上界 √(n-1)=2，触不到严格 >2σ——离群用例必须 9 点
    rows = [
        _entry(f"e{i}", retention_pct=v)
        for i, v in enumerate([10, 12, 14, 16, 18, 20, 22, 24, 200])
    ]
    # 200 离群 >2σ：点名且不进中位数
    result = export_report.aggregate(rows, "mode")
    row = result["rows"][0]
    assert row["median_retention_pct"] == 17.0, "中位数抗爆款绑架；均值 37.33 即红"
    assert row["outliers"] == ["e8"]


def test_signal_boundaries() -> None:
    for n, signal in [(9, "gray"), (10, "yellow"), (29, "yellow"), (30, "ok")]:
        rows = [_entry(f"e{i}") for i in range(n)]
        assert export_report.aggregate(rows, "mode")["rows"][0]["signal"] == signal, n


def test_zero_plays_excluded_and_missing_rates() -> None:
    rows = [
        _entry("e0", plays=0),
        _entry("e1", likes=100, shares=10),
        _entry("e2"),
    ]
    result = export_report.aggregate(rows, "mode")
    assert result["recorded"] == 3 and result["zero_plays_excluded"] == 1
    row = result["rows"][0]
    assert row["n"] == 2
    assert row["like_rate"] == 0.1, "缺失 likes 的条目剔除，不补 0（补 0 则 0.05）"
    assert row["share_rate"] == 0.01


def test_untraceable_bucket() -> None:
    rows = [_entry("e1", arc=None, angle=None)]
    result = export_report.aggregate(rows, "arc")
    assert result["rows"][0]["value"] == "不可考", "方案断链：投票真，骨架不可考"


def test_duration_bucket_boundaries() -> None:
    assert export_report.duration_bucket(None) == "未知"
    assert export_report.duration_bucket(29.9) == "<30s"
    assert export_report.duration_bucket(30.0) == "30-60s"
    assert export_report.duration_bucket(59.9) == "30-60s"
    assert export_report.duration_bucket(60.0) == "60-90s"
    assert export_report.duration_bucket(89.9) == "60-90s"
    assert export_report.duration_bucket(90.0) == "90s+"
    rows = [_entry("e1", duration_s=45.0), _entry("e2", duration_s=75.0)]
    values = [r["value"] for r in export_report.aggregate(rows, "duration_bucket")["rows"]]
    assert set(values) == {"30-60s", "60-90s"}


def test_health_lines_and_suggestions() -> None:
    rows = [
        _entry("e1", retention_3s=20.0, retention_pct=25.0),
        _entry("e2", retention_3s=40.0, retention_pct=35.0),
        _entry("e3", retention_pct=28.0),
    ]
    h = export_report.health(rows)
    assert h["line_3s"] == 32.0 and h["line_retention"] == 30.0
    assert "校准" in h["note"], "通用基准必须标注待回流校准"
    by_id = {(b["export_id"], b["metric"]): b for b in h["below"]}
    assert ("e1", "retention_3s") in by_id
    assert "钩子重选" in by_id[("e1", "retention_3s")]["suggestion"]
    assert ("e1", "retention_pct") in by_id
    assert "时长分析" in by_id[("e1", "retention_pct")]["suggestion"]
    assert ("e3", "retention_pct") in by_id
    assert ("e3", "retention_3s") not in by_id, "未录前3秒不判线，不编数据"
    assert not any(b["export_id"] == "e2" for b in h["below"])


def test_unknown_dimension_raises() -> None:
    with pytest.raises(ValueError):
        export_report.aggregate([], "watch_score")


def test_rpc_roundtrip(memory_db, tmp_path) -> None:
    from types import SimpleNamespace

    from dramaclip.api import export as export_api
    from dramaclip.infra.storage.repos import episodes as episodes_repo
    from dramaclip.infra.storage.repos import exports as exports_repo
    from dramaclip.infra.storage.repos import plans as plans_repo
    from dramaclip.infra.storage.repos import projects as projects_repo
    from dramaclip.transport.rpc import RpcDomainError

    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    project_id = str(projects_repo.create(memory_db, "报告剧", str(tmp_path))["id"])
    episodes_repo.replace_all(
        memory_db, project_id,
        [{"episode_number": 1, "source_path": str(source), "duration": 120.0}],
    )
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    plans_repo.create(
        memory_db, project_id, "full_narration", [episode_id],
        {"mode": "full_narration", "arc": "triumph", "timeline": []}, status="ready",
    )
    plan_id = str(plans_repo.list_by_project(memory_db, project_id)[0]["id"])
    export_id = str(exports_repo.create(memory_db, project_id, plan_id, "full_narration"))
    memory_db.execute(
        "UPDATE export_jobs SET status = 'completed', output_path = ?, duration_s = 75.0"
        " WHERE id = ?",
        (str(source), export_id),
    )
    memory_db.commit()
    context = SimpleNamespace(conn=memory_db)
    export_api.set_publish_data(context, {"export_id": export_id, "data": {
        "platform": "抖音", "plays": 2000, "retention_pct": 40.0, "shares": 100,
    }})
    report = export_api.publish_report(context, {"dimension": "duration_bucket"})
    assert report["rows"][0]["value"] == "60-90s"
    assert report["rows"][0]["share_rate"] == 0.05
    assert report["health"]["line_retention"] == 30.0
    arc_report = export_api.publish_report(context, {"dimension": "arc"})
    assert arc_report["rows"][0]["value"] == "triumph"
    with pytest.raises(RpcDomainError) as exc_info:
        export_api.publish_report(context, {"dimension": "watch_score"})
    assert exc_info.value.code == -32412
