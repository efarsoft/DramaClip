"""project.ensure_covers 双纪律（50 剧×579 集造数库实测教训）。

RPC dispatch 是单线程：补拍长堵会把 system.health 一起排队堵死，ServiceManager
便误判服务已死、杀进程重启——界面上是「全页 RPC 超时 + 服务反复重启」。两条纪律：
1. 死路径（源文件不在场）不配拉起 ffmpeg——每集三段 seek 回退就是三次进程开销，
   579 集死路径 ≈ 1900 次拉起；is_file() 预检让整库扫描回到毫秒级。
2. 单次调用限 _COVER_BUDGET_S 秒预算，欠账用 remaining 如实上报，渲染层涓流续拍
   （desktop/src/services/coverBackfill.ts：有进展才续轮）。
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import project as project_api
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.transport.rpc import Router, RpcRequest


def _request(request_id: int, method: str, params: dict[str, Any]) -> Any:
    return RpcRequest(id=request_id, method=method, params=params)


def _router(memory_db: sqlite3.Connection, tmp_path: Path) -> Router:
    context = SimpleNamespace(conn=memory_db, work_dir=tmp_path, data_dir=tmp_path)
    router = Router()
    project_api.register(router, context)  # type: ignore[arg-type]
    return router


def test_dead_sources_never_spawn_ffmpeg(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    def _boom(*args: Any, **kwargs: Any) -> bool:
        raise AssertionError("死路径不得拉起 ffmpeg")

    monkeypatch.setattr(project_api.cover_engine, "extract_cover", _boom)
    router = _router(memory_db, tmp_path)
    source = tmp_path / "drama"
    source.mkdir()
    created = router.dispatch(
        _request(1, "project.create", {"name": "死路径库", "source_path": str(source)})
    ).result
    project_id = str(created["id"])
    episodes_repo.replace_all(
        memory_db,
        project_id,
        [
            {
                "episode_number": index,
                "name": f"ep{index}",
                "source_path": str(source / f"missing-ep{index}.mp4"),
                "duration": 1.0,
            }
            for index in (1, 2)
        ],
    )

    result = router.dispatch(_request(2, "project.ensure_covers", {}))
    # 项目封面 + 两集封面全都补不成，但一次 ffmpeg 都没拉起，remaining 如实上报
    assert result.result == {"ok": True, "generated": 0, "remaining": 3}


def test_budget_zero_reports_all_remaining_without_work(
    monkeypatch: pytest.MonkeyPatch,
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
) -> None:
    monkeypatch.setattr(project_api, "_COVER_BUDGET_S", 0.0)
    calls: list[Path] = []

    def _fake_cover(video_path: Path, out_path: Path, **kwargs: Any) -> bool:
        calls.append(video_path)
        return True

    monkeypatch.setattr(project_api.cover_engine, "extract_cover", _fake_cover)
    router = _router(memory_db, tmp_path)
    source = tmp_path / "real"
    source.mkdir()
    shutil.copy(sample_video, source / "ep1.mp4")
    created = router.dispatch(
        _request(1, "project.create", {"name": "预算", "source_path": str(source)})
    ).result
    project_id = str(created["id"])
    router.dispatch(_request(2, "project.scan_episodes", {"project_id": project_id}))
    # 扫描自带的封面拍摄不算本 test 的观察面：清空封面与调用记录，只看预算分支
    memory_db.execute("UPDATE projects SET cover_path = NULL")
    memory_db.execute("UPDATE episodes SET cover_path = NULL")
    memory_db.commit()
    calls.clear()

    result = router.dispatch(_request(3, "project.ensure_covers", {}))
    assert result.result["generated"] == 0
    assert result.result["remaining"] == 2, "项目封面 + ep1，预算为零一个都不许拍"
    assert calls == []
