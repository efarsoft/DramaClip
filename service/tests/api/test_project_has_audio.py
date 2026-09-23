"""集级音轨判定 has_audio：扫描落库、project.get 出参布尔、旧数据保持未知。

缺音频轨告警行（09-10 §2.3①「⚠ N 集缺音频轨，无法转写」）的数据源。
三态纪律：True 有 / False 缺 / NULL 未重扫的旧集——取不到 ≠ 没有，界面不告警。
"""

from __future__ import annotations

import dataclasses
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from dramaclip.api import project as project_api
from dramaclip.transport.rpc import Router, RpcRequest


def _request(request_id: int, method: str, params: dict[str, Any]) -> Any:
    return RpcRequest(id=request_id, method=method, params=params)


def _scan_router(conn: sqlite3.Connection, work_dir: Path, *, data_dir: Path) -> Router:
    from types import SimpleNamespace

    context = SimpleNamespace(conn=conn, work_dir=work_dir, data_dir=data_dir)
    router = Router()
    project_api.register(router, context)  # type: ignore[arg-type]
    return router


def _scan_one(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> tuple[Router, str]:
    shutil.copy(sample_video, tmp_path / "ep1.mp4")
    router = _scan_router(memory_db, tmp_path / "cache", data_dir=tmp_path)
    created = router.dispatch(
        _request(1, "project.create", {"name": "音轨", "source_path": str(tmp_path)})
    )
    return router, str(created.result["id"])


def test_scan_records_has_audio_true(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    router, project_id = _scan_one(memory_db, tmp_path, sample_video)
    scanned = router.dispatch(
        _request(2, "project.scan_episodes", {"project_id": project_id})
    ).result
    assert scanned[0]["has_audio"] is True, "sample_video 带 440Hz 正弦音轨"
    detail = router.dispatch(_request(3, "project.get", {"project_id": project_id})).result
    assert detail["episodes"][0]["has_audio"] is True, "库里是 0/1，出参必须还原成布尔"


def test_scan_records_has_audio_false(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_probe = project_api.probe.probe

    def silent_probe(path: Path) -> Any:
        return dataclasses.replace(real_probe(path), has_audio=False)

    monkeypatch.setattr(project_api.probe, "probe", silent_probe)
    router, project_id = _scan_one(memory_db, tmp_path, sample_video)
    scanned = router.dispatch(
        _request(2, "project.scan_episodes", {"project_id": project_id})
    ).result
    assert scanned[0]["has_audio"] is False
    detail = router.dispatch(_request(3, "project.get", {"project_id": project_id})).result
    assert detail["episodes"][0]["has_audio"] is False


def test_legacy_rows_stay_unknown(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    router, project_id = _scan_one(memory_db, tmp_path, sample_video)
    router.dispatch(_request(2, "project.scan_episodes", {"project_id": project_id}))
    # 模拟迁移前的旧集：列在、值未探过
    memory_db.execute("UPDATE episodes SET has_audio = NULL")
    memory_db.commit()
    detail = router.dispatch(_request(3, "project.get", {"project_id": project_id})).result
    assert detail["episodes"][0]["has_audio"] is None, "NULL 原样出参，不猜成 False"
