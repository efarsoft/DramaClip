"""export 命名空间：list_works（跨项目作品库）。"""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from dramaclip.api import export as export_api
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.rpc import Router, RpcRequest


class Harness:
    def __init__(self, conn: sqlite3.Connection) -> None:
        from types import SimpleNamespace

        self.context = SimpleNamespace(conn=conn)
        self.router = Router()
        export_api.register(self.router, self.context)  # type: ignore[arg-type]

    def rpc(self, method: str, params: dict[str, Any]) -> Any:
        return self.router.dispatch(RpcRequest(id=method, method=method, params=params)).result


def _seed_works(conn: sqlite3.Connection) -> None:
    p1 = str(projects_repo.create(conn, "甲项目", "D:/a")["id"])
    p2 = str(projects_repo.create(conn, "乙项目", "D:/b")["id"])
    plan1 = str(plans_repo.create(conn, p1, "raw_clip", [], {"timeline": []})["id"])
    plan2 = str(plans_repo.create(conn, p2, "intro_narration", [], {"timeline": []})["id"])
    failed = exports_repo.create(conn, p1, plan1, "raw_clip")
    exports_repo.mark_failed(conn, failed, "编码失败")
    first = exports_repo.create(conn, p1, plan1, "raw_clip")
    exports_repo.mark_completed(conn, first, "D:/out/a.mp4")
    time.sleep(0.01)  # completed_at 毫秒序稳定
    second = exports_repo.create(conn, p2, plan2, "intro_narration")
    exports_repo.mark_completed(conn, second, "D:/out/b.mp4")


def test_list_works_cross_project_ordered(memory_db: sqlite3.Connection) -> None:
    harness = Harness(memory_db)
    _seed_works(memory_db)
    works = harness.rpc("export.list_works", {})
    # 失败记录被排除，按完成时间倒序
    assert [work["project_name"] for work in works] == ["乙项目", "甲项目"]
    assert works[0]["narration_mode"] == "intro_narration"
    assert works[0]["output_path"] == "D:/out/b.mp4"


def test_list_works_limit(memory_db: sqlite3.Connection) -> None:
    harness = Harness(memory_db)
    _seed_works(memory_db)
    works = harness.rpc("export.list_works", {"limit": 1})
    assert len(works) == 1


def test_list_works_empty(memory_db: sqlite3.Connection) -> None:
    harness = Harness(memory_db)
    assert harness.rpc("export.list_works", {}) == []
