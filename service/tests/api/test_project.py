"""api.project：仓储联动 + 真实扫描 + 自然排序。"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from typing import Any

from dramaclip.api import project as project_api
from dramaclip.transport.rpc import Router


def _router(conn: sqlite3.Connection) -> Router:
    from types import SimpleNamespace

    context = SimpleNamespace(conn=conn)
    router = Router()
    project_api.register(router, context)  # type: ignore[arg-type]
    return router


def test_natural_key_orders_numbers() -> None:
    names = ["ep10.mp4", "ep2.mp4", "ep1.mp4"]
    assert sorted(names, key=project_api.natural_key) == ["ep1.mp4", "ep2.mp4", "ep10.mp4"]


def test_create_and_get_roundtrip(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    router = _router(memory_db)
    created = router.dispatch(
        _request(1, "project.create", {"name": "复仇千金", "source_path": str(tmp_path)})
    )
    project = created.result
    assert project["name"] == "复仇千金"
    detail = router.dispatch(_request(2, "project.get", {"project_id": project["id"]}))
    assert detail.result["project"]["id"] == project["id"]
    assert detail.result["episodes"] == []


def test_create_rejects_missing_dir(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    router = _router(memory_db)
    response = router.dispatch(
        _request(1, "project.create", {"name": "x", "source_path": str(tmp_path / "nope")})
    )
    assert response.error is not None and response.error.code == -32102


def test_scan_episodes_registers_videos(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    for number in (2, 10, 1):
        shutil.copy(sample_video, tmp_path / f"ep{number}.mp4")
    (tmp_path / "readme.txt").write_text("not video", encoding="utf-8")
    router = _scan_router(memory_db, tmp_path / "cache", data_dir=tmp_path)
    project = router.dispatch(
        _request(1, "project.create", {"name": "p", "source_path": str(tmp_path)})
    ).result

    scanned = router.dispatch(
        _request(2, "project.scan_episodes", {"project_id": project["id"]})
    ).result
    numbers = [item["episode_number"] for item in scanned]
    assert numbers == [1, 2, 3], "顺序重编 1..N"
    assert [item["name"] for item in scanned] == ["ep1", "ep2", "ep10"], "文件按自然排序"
    assert all(item["duration"] > 2 for item in scanned)

    detail = router.dispatch(_request(3, "project.get", {"project_id": project["id"]})).result
    assert [ep["episode_number"] for ep in detail["episodes"]] == [1, 2, 3]
    assert detail["project"]["episode_count"] == 3


def test_scan_rejects_empty_dir(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    router = _router(memory_db)
    project = router.dispatch(
        _request(1, "project.create", {"name": "p", "source_path": str(tmp_path)})
    ).result
    response = router.dispatch(
        _request(2, "project.scan_episodes", {"project_id": project["id"]})
    )
    assert response.error is not None and response.error.code == -32103


def test_delete_cascades(memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path) -> None:
    shutil.copy(sample_video, tmp_path / "ep1.mp4")
    router = _router(memory_db)
    project = router.dispatch(
        _request(1, "project.create", {"name": "p", "source_path": str(tmp_path)})
    ).result
    router.dispatch(_request(2, "project.scan_episodes", {"project_id": project["id"]}))
    assert router.dispatch(_request(3, "project.delete", {"project_id": project["id"]})).result == {
        "ok": True
    }
    response = router.dispatch(_request(4, "project.get", {"project_id": project["id"]}))
    assert response.error is not None and response.error.code == -32101


def _request(request_id: int, method: str, params: dict[str, Any]) -> Any:
    from dramaclip.transport.rpc import RpcRequest

    return RpcRequest(id=request_id, method=method, params=params)


def _scan_router(conn: sqlite3.Connection, work_dir: Path, *, data_dir: Path) -> Router:
    from types import SimpleNamespace

    context = SimpleNamespace(conn=conn, work_dir=work_dir, data_dir=data_dir)
    router = Router()
    project_api.register(router, context)  # type: ignore[arg-type]
    return router


def test_scan_generates_cover(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    router = _scan_router(memory_db, tmp_path / "cache", data_dir=tmp_path)
    shutil.copy(sample_video, tmp_path / "ep1.mp4")
    created = router.dispatch(
        _request(1, "project.create", {"name": "封面", "source_path": str(tmp_path)})
    )
    project_id = created.result["id"]
    router.dispatch(_request(2, "project.scan_episodes", {"project_id": project_id}))
    detail = router.dispatch(_request(3, "project.get", {"project_id": project_id}))
    cover = detail.result["project"].get("cover_path")
    assert cover is not None and Path(cover).is_file()


def test_ensure_covers_idempotent(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    router = _scan_router(memory_db, tmp_path / "cache", data_dir=tmp_path)
    shutil.copy(sample_video, tmp_path / "ep1.mp4")
    created = router.dispatch(
        _request(1, "project.create", {"name": "补封面", "source_path": str(tmp_path)})
    )
    project_id = created.result["id"]
    router.dispatch(_request(2, "project.scan_episodes", {"project_id": project_id}))
    result = router.dispatch(_request(3, "project.ensure_covers", {}))
    assert result.result == {"ok": True, "generated": 0, "remaining": 0}


def test_reorder_episodes(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    router = _scan_router(memory_db, tmp_path / "cache", data_dir=tmp_path)
    for number in (1, 2, 3):
        shutil.copy(sample_video, tmp_path / f"ep{number}.mp4")
    created = router.dispatch(
        _request(1, "project.create", {"name": "排序", "source_path": str(tmp_path)})
    )
    project_id = created.result["id"]
    router.dispatch(_request(2, "project.scan_episodes", {"project_id": project_id}))
    detail = router.dispatch(_request(3, "project.get", {"project_id": project_id}))
    episodes = detail.result["episodes"]
    ordered = [episodes[2]["id"], episodes[0]["id"], episodes[1]["id"]]
    result = router.dispatch(
        _request(4, "project.reorder_episodes", {"project_id": project_id, "episode_ids": ordered})
    )
    assert result.result == {"ok": True}
    detail = router.dispatch(_request(5, "project.get", {"project_id": project_id}))
    numbers = [ep["episode_number"] for ep in detail.result["episodes"]]
    assert numbers == [1, 2, 3], "重排后编号连续"
    names = [ep["name"] for ep in detail.result["episodes"]]
    assert names == ["ep3", "ep1", "ep2"], "手动顺序生效"


def test_reorder_rejects_mismatched_ids(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    router = _scan_router(memory_db, tmp_path / "cache", data_dir=tmp_path)
    shutil.copy(sample_video, tmp_path / "ep1.mp4")
    created = router.dispatch(
        _request(1, "project.create", {"name": "校验", "source_path": str(tmp_path)})
    )
    project_id = created.result["id"]
    router.dispatch(_request(2, "project.scan_episodes", {"project_id": project_id}))
    response = router.dispatch(
        _request(
            3,
            "project.reorder_episodes",
            {"project_id": project_id, "episode_ids": ["bad-id"]},
        )
    )
    assert response.error is not None


def test_scan_generates_episode_covers(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    router = _scan_router(memory_db, tmp_path / "cache", data_dir=tmp_path)
    shutil.copy(sample_video, tmp_path / "ep1.mp4")
    created = router.dispatch(
        _request(1, "project.create", {"name": "集封面", "source_path": str(tmp_path)})
    )
    project_id = created.result["id"]
    router.dispatch(_request(2, "project.scan_episodes", {"project_id": project_id}))
    detail = router.dispatch(_request(3, "project.get", {"project_id": project_id}))
    covers = [ep.get("cover_path") for ep in detail.result["episodes"]]
    assert all(cover is not None and Path(str(cover)).is_file() for cover in covers)
