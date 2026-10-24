"""跨稿人物介绍的 prior_texts 生产链注入：查询口径（只取 ready/最近优先）+ 透传。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

from dramaclip.api.narration_plans import _collect_prior_texts
from dramaclip.engines.narration import script_driver
from dramaclip.engines.narration.models import PlanData
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo


def _seed_plan(
    memory_db: sqlite3.Connection,
    project_id: str,
    *,
    mode: str = "full_narration",
    status: str = "ready",
    text: str = "",
) -> str:
    plan_data = PlanData(
        mode=mode,
        timeline=[],
        narration_texts=[{"id": "n1", "text": text}] if text else [],
    )
    plans_repo.create(
        memory_db, project_id, mode, [], plan_data.model_dump(),
        status=status,
    )
    rows = plans_repo.list_by_project(memory_db, project_id)
    return str(rows[0]["id"])


def test_collects_only_ready_latest_first(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    """draft（缺陷稿）不进比对基准；最近优先；limit 截断。"""
    project_id = str(projects_repo.create(memory_db, "跨稿剧", str(tmp_path))["id"])
    _seed_plan(memory_db, project_id, status="draft", text="缺陷稿不该出现")
    for index in range(4):
        _seed_plan(memory_db, project_id, text=f"既往稿{index}")
    context = SimpleNamespace(conn=memory_db)
    texts = _collect_prior_texts(context, project_id)
    assert len(texts) == 3
    assert all("缺陷稿" not in text for text in texts)


def test_empty_and_blank_plans_skipped(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    project_id = str(projects_repo.create(memory_db, "空稿剧", str(tmp_path))["id"])
    _seed_plan(memory_db, project_id, status="ready", text="")
    _seed_plan(memory_db, project_id, status="ready", text="有稿的一条")
    context = SimpleNamespace(conn=memory_db)
    texts = _collect_prior_texts(context, project_id)
    assert texts == ["有稿的一条"], "空稿/无槽位文本的方案跳过，不占 limit 名额"


def test_driver_parses_prior_texts_from_settings() -> None:
    settings = {"_prior_texts_json": '["甲稿", "乙稿"]'}
    assert script_driver._prior_texts_of(settings) == ["甲稿", "乙稿"]
    assert script_driver._prior_texts_of({}) is None
    assert script_driver._prior_texts_of({"_prior_texts_json": "坏json"}) is None



