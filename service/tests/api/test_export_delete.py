"""export.delete（09-10 §3.4 危险操作规矩）：文件先移入 <data>/.trash/<日期>/ 再删行。

钉四件事：① 成片与封面都搬（不搬封面就成孤儿）；② 盘上已缺的文件如实报
missing、不挡删行；③ 围栏——产物不在数据目录内整单拒绝（宁留记录，不产无法
追溯的孤儿文件）；④ 同名冲突加前缀，不覆盖回收站里已有的东西。
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from dramaclip.api import export as export_api
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.rpc import Router, RpcRequest


class Harness:
    def __init__(self, conn: sqlite3.Connection, data_dir: Path) -> None:
        self.context = SimpleNamespace(conn=conn, data_dir=data_dir)
        self.router = Router()
        export_api.register(self.router, self.context)  # type: ignore[arg-type]

    def dispatch(self, method: str, params: dict[str, Any]) -> Any:
        return self.router.dispatch(RpcRequest(id=method, method=method, params=params))

    def rpc(self, method: str, params: dict[str, Any]) -> Any:
        response = self.dispatch(method, params)
        if response.error is not None:
            raise AssertionError(
                f"{method} RPC 错误: [{response.error.code}] {response.error.message}"
            )
        return response.result


def _seed_completed(
    conn: sqlite3.Connection, data_dir: Path, *, with_cover: bool = True
) -> tuple[str, Path, Path | None]:
    """一条已完成成片：产物（与封面）真落盘在数据目录内。返回 (export_id, 产物, 封面)。"""
    project_id = str(projects_repo.create(conn, "删除剧", str(data_dir))["id"])
    plan_id = str(plans_repo.create(conn, project_id, "raw_clip", [], {"timeline": []})["id"])
    export_id = exports_repo.create(conn, project_id, plan_id, "raw_clip")
    out_dir = data_dir / "outputs" / project_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"film_{export_id[:6]}.mp4"
    out_path.write_bytes(b"film")
    exports_repo.mark_completed(conn, export_id, str(out_path))
    cover_path: Path | None = None
    if with_cover:
        cover_dir = data_dir / "covers" / "exports"
        cover_dir.mkdir(parents=True, exist_ok=True)
        cover_path = cover_dir / f"{export_id}.jpg"
        cover_path.write_bytes(b"jpg")
        exports_repo.set_cover(conn, export_id, str(cover_path))
    return export_id, out_path, cover_path


def test_delete_moves_output_and_cover_then_drops_row(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    harness = Harness(memory_db, data_dir)
    export_id, out_path, cover_path = _seed_completed(memory_db, data_dir)

    result = harness.rpc("export.delete", {"export_id": export_id})
    assert result["ok"] is True and result["missing"] == []

    trash_dir = data_dir / ".trash" / date.today().isoformat()
    assert sorted(result["trashed"]) == sorted(
        [str(trash_dir / out_path.name), str(trash_dir / (cover_path.name if cover_path else ""))]
    )
    assert not out_path.exists(), "成片必须已搬走"
    assert cover_path is not None and not cover_path.exists(), "封面必须跟着搬，不留孤儿"
    assert (trash_dir / out_path.name).is_file() and (trash_dir / cover_path.name).is_file()
    assert exports_repo.get(memory_db, export_id) is None, "记录行已删"
    assert harness.rpc("export.list_works", {}) == []


def test_delete_reports_missing_files_but_still_drops_row(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """记录指向的东西盘上已经没了：如实报 missing，删行照走（本来就没文件可恢复）。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    harness = Harness(memory_db, data_dir)
    export_id, out_path, _cover = _seed_completed(memory_db, data_dir, with_cover=False)
    out_path.unlink()

    result = harness.rpc("export.delete", {"export_id": export_id})
    assert result["ok"] is True and result["trashed"] == []
    assert result["missing"] == [str(out_path)]
    assert exports_repo.get(memory_db, export_id) is None


def test_delete_fence_rejects_paths_outside_data_dir(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """围栏：产物不在数据目录内 → 整单拒绝（-32408），记录保留、文件不动。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"film")
    harness = Harness(memory_db, data_dir)
    export_id, _out, _cover = _seed_completed(memory_db, data_dir, with_cover=False)
    exports_repo.mark_completed(memory_db, export_id, str(outside))

    response = harness.dispatch("export.delete", {"export_id": export_id})
    assert response.error is not None and response.error.code == -32408
    assert outside.is_file(), "围栏拒绝时一个字节都不许动"
    assert exports_repo.get(memory_db, export_id) is not None, "整单拒绝 = 记录保留"


def test_delete_not_found(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    harness = Harness(memory_db, tmp_path)
    response = harness.dispatch("export.delete", {"export_id": "nonexistent"})
    assert response.error is not None and response.error.code == -32404
    assert "nonexistent" in response.error.message


def test_delete_name_collision_gets_id_prefix(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """回收站里已有同名文件：加 export_id 前缀，不覆盖已回收的东西。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    harness = Harness(memory_db, data_dir)
    export_id, out_path, _cover = _seed_completed(memory_db, data_dir, with_cover=False)
    trash_dir = data_dir / ".trash" / date.today().isoformat()
    trash_dir.mkdir(parents=True)
    prior = "先前回收的同名文件".encode()
    (trash_dir / out_path.name).write_bytes(prior)

    result = harness.rpc("export.delete", {"export_id": export_id})
    expected = trash_dir / f"{export_id[:6]}_{out_path.name}"
    assert result["trashed"] == [str(expected)]
    assert expected.is_file()
    assert (trash_dir / out_path.name).read_bytes() == prior, "旧回收物原样保留"
