"""W8 发布数据回流：录入校验（宁拒收不存脏数据）+ 读取链路（get/works 列表）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import export as export_api
from dramaclip.engines.narration.models import PlanData, TimelineSegment
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.rpc import RpcDomainError


def _seed(memory_db: sqlite3.Connection, tmp_path: Path) -> str:
    """export_jobs.narration_plan_id 有真外键（坑⑫）：计划行必须真建，假 id 必炸。"""
    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    project_id = str(projects_repo.create(memory_db, "回流剧", str(tmp_path))["id"])
    episodes_repo.replace_all(
        memory_db,
        project_id,
        [{"episode_number": 1, "source_path": str(source), "duration": 120.0}],
    )
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    plan_data = PlanData(
        mode="full_narration",
        timeline=[
            TimelineSegment(episode_id=episode_id, start=0.0, end=10.0, audio="narration")
        ],
    )
    plans_repo.create(
        memory_db, project_id, "full_narration", [episode_id],
        plan_data.model_dump(), status="ready",
    )
    plan_id = str(plans_repo.list_by_project(memory_db, project_id)[0]["id"])
    return str(exports_repo.create(memory_db, project_id, plan_id, "full_narration"))


def _context(memory_db: sqlite3.Connection) -> SimpleNamespace:
    return SimpleNamespace(conn=memory_db)


def _valid_data() -> dict[str, Any]:
    return {"platform": "抖音", "plays": 12000, "retention_pct": 32.5}


def test_roundtrip_via_get_and_works_list(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    export_id = _seed(memory_db, tmp_path)
    context = _context(memory_db)
    result = export_api.set_publish_data(
        context, {"export_id": export_id, "data": {**_valid_data(), "likes": 300}}
    )
    assert result["ok"] is True
    stored = result["publish_data"]
    assert stored["platform"] == "抖音" and stored["plays"] == 12000
    assert stored["retention_pct"] == 32.5 and stored["likes"] == 300
    assert stored["recorded_at"] > 0, "录入时刻入账（harness 的时序维度）"

    got = export_api.get_export(context, {"export_id": export_id})
    assert got["publish_data"] == stored

    works = exports_repo.list_completed_works(memory_db, limit=20)
    assert all(w["publish_data"] is None for w in works), (
        "pending 成片不进作品库（现状行为不因回流改变）——本用例只守列表形状不炸"
    )


def test_rejects_bad_platform_and_ranges(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    export_id = _seed(memory_db, tmp_path)
    context = _context(memory_db)
    bad_payloads = [
        {"platform": "微视", "plays": 1, "retention_pct": 10},
        {"plays": 1, "retention_pct": 10},
        {"platform": "抖音", "retention_pct": 10},
        {"platform": "抖音", "plays": 1},
        {"platform": "抖音", "plays": -1, "retention_pct": 10},
        {"platform": "抖音", "plays": 1, "retention_pct": 101},
        {"platform": "抖音", "plays": 1, "retention_pct": 10, "likes": -5},
    ]
    for data in bad_payloads:
        with pytest.raises(RpcDomainError) as exc_info:
            export_api.set_publish_data(context, {"export_id": export_id, "data": data})
        assert exc_info.value.code == -32410, data
    row = exports_repo.get(memory_db, export_id)
    assert row is not None and row["publish_data"] is None, "拒收的脏数据一个都不落库"


def test_optional_fields_and_clear(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    export_id = _seed(memory_db, tmp_path)
    context = _context(memory_db)
    export_api.set_publish_data(
        context,
        {"export_id": export_id, "data": {**_valid_data(), "published_at": "2026-10-23"}},
    )
    got = export_api.get_export(context, {"export_id": export_id})
    assert got["publish_data"]["published_at"] == "2026-10-23"
    assert got["publish_data"]["likes"] is None, "可选字段缺省为 None，不编 0"

    export_api.set_publish_data(context, {"export_id": export_id, "data": None})
    got = export_api.get_export(context, {"export_id": export_id})
    assert got["publish_data"] is None, "清除录入＝回未录入态"


def test_missing_export_is_404_style(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    with pytest.raises(RpcDomainError) as exc_info:
        export_api.set_publish_data(
            _context(memory_db), {"export_id": "nope", "data": _valid_data()}
        )
    assert exc_info.value.code == -32404


def test_extended_fields_roundtrip(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    export_id = _seed(memory_db, tmp_path)
    result = export_api.set_publish_data(
        _context(memory_db),
        {"export_id": export_id, "data": {
            **_valid_data(), "shares": 45, "retention_3s": 41.256,
            "video_id": "https://v.douyin.com/abc/",
        }},
    )
    stored = result["publish_data"]
    assert stored["shares"] == 45
    assert stored["retention_3s"] == 41.26, "与 retention_pct 同口径 round 2"
    assert stored["video_id"] == "https://v.douyin.com/abc/"


def test_extended_fields_default_none(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    export_id = _seed(memory_db, tmp_path)
    result = export_api.set_publish_data(
        _context(memory_db), {"export_id": export_id, "data": _valid_data()}
    )
    stored = result["publish_data"]
    assert stored["shares"] is None and stored["retention_3s"] is None
    assert stored["video_id"] is None, "可选字段缺省为 None，不编 0/空串"


def test_rejects_bad_extended_fields(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    export_id = _seed(memory_db, tmp_path)
    context = _context(memory_db)
    bad = [
        {"shares": -1}, {"shares": "abc"}, {"retention_3s": 101},
        {"retention_3s": -0.5}, {"retention_3s": "x"}, {"video_id": "字" * 201},
    ]
    for extra in bad:
        with pytest.raises(RpcDomainError) as exc_info:
            export_api.set_publish_data(
                context, {"export_id": export_id, "data": {**_valid_data(), **extra}}
            )
        assert exc_info.value.code == -32410, extra
    row = exports_repo.get(memory_db, export_id)
    assert row is not None and row["publish_data"] is None, "拒收的脏数据一个都不落库"


def test_video_id_conflict_conservative(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    # projects.source_path 有 UNIQUE 约束：两条独立成片须用不同源目录
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    export_a = _seed(memory_db, tmp_path / "a")
    export_b = _seed(memory_db, tmp_path / "b")
    context = _context(memory_db)
    data = {**_valid_data(), "video_id": "douyin-123"}
    export_api.set_publish_data(context, {"export_id": export_a, "data": data})
    # 同平台同作品 ID 绑另一条成片 → 宁拒不错配
    with pytest.raises(RpcDomainError) as exc_info:
        export_api.set_publish_data(context, {"export_id": export_b, "data": data})
    assert exc_info.value.code == -32410
    assert exports_repo.get(memory_db, export_b)["publish_data"] is None
    # 同一条成片重录同 ID → 覆盖（W8 现状），排除自身不算冲突
    export_api.set_publish_data(
        context, {"export_id": export_a, "data": {**data, "plays": 999}}
    )
    assert exports_repo.get(memory_db, export_a)["publish_data"]["plays"] == 999
    # 跨平台同 ID → 不冲突（平台各自编号）
    export_api.set_publish_data(
        context, {"export_id": export_b, "data": {**data, "platform": "快手"}}
    )
    assert exports_repo.get(memory_db, export_b)["publish_data"]["video_id"] == "douyin-123"
