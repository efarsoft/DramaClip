"""结算 CSV 批量导入（W14·条件③对账）：按 作品ID 匹配成片回填结算维度。

宁拒录不错配：匹配不到成片 / 成片尚无发布记录 / 金额不是数字 → skipped 带原因。
只回填记录不做对账逻辑（「不做变现化工程」裁决边界内）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from dramaclip.api import export as export_api
from dramaclip.infra.storage.repos import exports as exports_repo

CSV_TEXT = "作品ID,结算金额,发布账号\nvid-1,128.5,主号\nvid-2,56,小号\n"


def _publish(
    memory_db: sqlite3.Connection, export_id: str, video_id: str, platform: str = "抖音"
) -> None:
    exports_repo.set_publish_data(
        memory_db,
        export_id,
        {"platform": platform, "plays": 100, "retention_pct": 50, "video_id": video_id},
    )


def _seed_with_plan(memory_db: sqlite3.Connection, tmp_path: Path, video_id: str) -> str:
    """真计划行 + 发布记录（export_jobs 外键坑⑫ + 匹配源）。"""
    from dramaclip.engines.narration.models import PlanData, TimelineSegment
    from dramaclip.infra.storage.repos import episodes as episodes_repo
    from dramaclip.infra.storage.repos import plans as plans_repo
    from dramaclip.infra.storage.repos import projects as projects_repo

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
    export_id = str(exports_repo.create(memory_db, project_id, plan_id, "full_narration"))
    _publish(memory_db, export_id, video_id)
    return export_id


def test_csv_backfills_settlement_and_account(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    export_id = _seed_with_plan(memory_db, tmp_path, "vid-1")

    result = export_api.import_settlement_csv(
        SimpleNamespace(conn=memory_db), {"csv_text": CSV_TEXT}
    )
    assert result["ok"] is True
    assert result["matched"] == 1
    row = exports_repo.get(memory_db, export_id)
    publish = row["publish_data"]  # repo 层已解析为 dict
    assert publish["settlement_amount"] == 128.5
    assert publish["publish_account"] == "主号"
    assert publish["video_id"] == "vid-1"
    assert publish["platform"] == "抖音"


def test_csv_skips_rows_without_match(memory_db: sqlite3.Connection) -> None:
    """匹配不到成片的行宁拒录不错配：skipped 带原因，不写任何脏数据。"""
    result = export_api.import_settlement_csv(
        SimpleNamespace(conn=memory_db), {"csv_text": CSV_TEXT}
    )
    assert result["matched"] == 0
    assert any("没有匹配到成片" in item["reason"] for item in result["skipped"])


def test_csv_rejects_missing_video_id_column(memory_db: sqlite3.Connection) -> None:
    from dramaclip.transport.rpc import RpcDomainError

    with pytest.raises(RpcDomainError, match="作品ID"):
        export_api.import_settlement_csv(
            SimpleNamespace(conn=memory_db), {"csv_text": "金额,账号\n56,小号"}
        )


def test_csv_skips_non_numeric_amount(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    _seed_with_plan(memory_db, tmp_path, "vid-1")
    csv_text = "作品ID,结算金额,发布账号\nvid-1,abc,主号\n"
    result = export_api.import_settlement_csv(
        SimpleNamespace(conn=memory_db), {"csv_text": csv_text}
    )
    assert result["matched"] == 0
    assert any("结算金额不是数字" in item["reason"] for item in result["skipped"])


