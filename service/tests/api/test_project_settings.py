"""项目级参数：K、转写档位、风格、字幕预设的覆盖值都存这里（默认+覆盖机制）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

from dramaclip.api import project as project_api
from dramaclip.infra import jobs as jobs_mod
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import Router, RpcRequest


def _router(memory_db: sqlite3.Connection, tmp_path: Path) -> Router:
    context = SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "cache" / "analysis",
        settings={},
        notifier=Notifier(lambda _m: None),
        job_store=jobs_mod.JobStore(memory_db),
        cancel_events={},
    )
    router = Router()
    project_api.register(router, context)  # type: ignore[arg-type]
    return router


def _call(router: Router, method: str, params: dict) -> dict:
    response = router.dispatch(RpcRequest(id=method, method=method, params=params))
    assert response.error is None, response.error
    return response.result  # type: ignore[return-value]


def test_update_then_read_back(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    router = _router(memory_db, tmp_path)
    project = _call(router, "project.create", {"name": "参数剧", "source_path": str(tmp_path)})
    _call(
        router, "project.update_settings",
        {"project_id": project["id"], "settings": {"variant_count": 3, "transcribe_mode": "full"}},
    )
    fetched = _call(router, "project.get", {"project_id": project["id"]})
    assert fetched["project"]["settings"] == {"variant_count": 3, "transcribe_mode": "full"}


def test_update_merges_not_replaces(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    router = _router(memory_db, tmp_path)
    project = _call(router, "project.create", {"name": "合并剧", "source_path": str(tmp_path)})
    _call(router, "project.update_settings",
          {"project_id": project["id"], "settings": {"variant_count": 3}})
    _call(router, "project.update_settings",
          {"project_id": project["id"], "settings": {"subtitle_preset": "karaoke-pop"}})
    settings = _call(router, "project.get", {"project_id": project["id"]})["project"]["settings"]
    assert settings == {"variant_count": 3, "subtitle_preset": "karaoke-pop"}


def test_null_value_clears_key(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    """恢复默认 = 把该键置 null，而不是删整个 settings。"""
    router = _router(memory_db, tmp_path)
    project = _call(router, "project.create", {"name": "清键剧", "source_path": str(tmp_path)})
    _call(router, "project.update_settings",
          {"project_id": project["id"], "settings": {"variant_count": 5, "style_id": "suspense"}})
    _call(router, "project.update_settings",
          {"project_id": project["id"], "settings": {"variant_count": None}})
    settings = _call(router, "project.get", {"project_id": project["id"]})["project"]["settings"]
    assert settings == {"style_id": "suspense"}


def test_list_all_also_exposes_settings(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    """project.list 也要带出 settings——剧库卡片和"恢复默认"按钮都要读它。"""
    router = _router(memory_db, tmp_path)
    project = _call(router, "project.create", {"name": "列表剧", "source_path": str(tmp_path)})
    _call(router, "project.update_settings",
          {"project_id": project["id"], "settings": {"variant_count": 4}})
    rows = _call(router, "project.list", {})
    assert rows[0]["settings"] == {"variant_count": 4}


def test_duplicate_copies_settings(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    """复制剧通常是为了同参数换素材再产一批，覆盖值应当带过去。"""
    router = _router(memory_db, tmp_path)
    project = _call(router, "project.create", {"name": "复制剧", "source_path": str(tmp_path)})
    _call(router, "project.update_settings",
          {"project_id": project["id"], "settings": {"variant_count": 6}})
    copy = _call(router, "project.duplicate", {"project_id": project["id"]})
    assert copy["settings"] == {"variant_count": 6}
    original = _call(router, "project.get", {"project_id": project["id"]})
    assert original["project"]["settings"] == {"variant_count": 6}, "源项目不受影响"


def test_settings_never_a_string_on_the_wire(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    """create 返回值也被前端当 Project 用；settings 一律是对象（plans.plan_data 同套路）。"""
    router = _router(memory_db, tmp_path)
    project = _call(router, "project.create", {"name": "空参剧", "source_path": str(tmp_path)})
    assert project["settings"] == {}
    assert isinstance(project["settings"], dict)


def test_corrupt_settings_blob_degrades_to_empty(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """库里的 settings 被写坏时不能炸应用：等价于"没有任何覆盖"。"""
    router = _router(memory_db, tmp_path)
    project = _call(router, "project.create", {"name": "坏库剧", "source_path": str(tmp_path)})
    memory_db.execute("UPDATE projects SET settings = ? WHERE id = ?", ("{broken", project["id"]))
    fetched = _call(router, "project.get", {"project_id": project["id"]})
    assert fetched["project"]["settings"] == {}
    _call(router, "project.update_settings",
          {"project_id": project["id"], "settings": {"style_id": "suspense"}})
    fetched = _call(router, "project.get", {"project_id": project["id"]})
    assert fetched["project"]["settings"] == {"style_id": "suspense"}, "坏值后可直接覆盖写回"


def test_non_object_settings_is_rejected(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    router = _router(memory_db, tmp_path)
    project = _call(router, "project.create", {"name": "坏值剧", "source_path": str(tmp_path)})
    response = router.dispatch(RpcRequest(
        id=1, method="project.update_settings",
        params={"project_id": project["id"], "settings": [1, 2]}
    ))
    assert response.error is not None
    assert response.error.code == -32104


def test_missing_project_is_domain_error(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    router = _router(memory_db, tmp_path)
    response = router.dispatch(RpcRequest(
        id=1, method="project.update_settings", params={"project_id": "nope", "settings": {}}
    ))
    assert response.error is not None
    assert response.error.code == -32101
