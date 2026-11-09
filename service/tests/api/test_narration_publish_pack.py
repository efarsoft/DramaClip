"""narration.publish_pack RPC：与详情页同一份库快照，规格与注入在服务端。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from dramaclip.api import narration as narration_api
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.rpc import Router, RpcRequest


def _seed(memory_db: sqlite3.Connection, tmp_path: Path) -> str:
    project_id = str(projects_repo.create(memory_db, "发布剧", str(tmp_path))["id"])
    plan_id = str(
        plans_repo.create(
            memory_db, project_id, "full_narration", ["ep1"],
            {"mode": "full_narration", "timeline": []},
        )["id"]
    )
    plans_repo.set_titles(
        memory_db, plan_id,
        json.dumps([{"text": "当选标题", "selected": True}], ensure_ascii=False),
    )
    plans_repo.set_publish_meta(
        memory_db, plan_id,
        json.dumps({"caption": "文案", "tags": ["爽剧"]}, ensure_ascii=False),
    )
    return plan_id


def test_publish_pack_rpc(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    plan_id = _seed(memory_db, tmp_path)
    context = SimpleNamespace(conn=memory_db, settings={})
    router = Router()
    narration_api.register(router, context)  # type: ignore[arg-type]
    response = router.dispatch(
        RpcRequest(id="1", method="narration.publish_pack", params={"plan_id": plan_id})
    )
    assert response.error is None
    result: dict[str, Any] = response.result
    assert result["title"] == "当选标题"
    assert "好剧推荐" in result["tags"]
    assert result["platforms"]["小红书"]["cover_ratio"] == [3, 4]


def test_publish_pack_missing_plan(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    context = SimpleNamespace(conn=memory_db, settings={})
    router = Router()
    narration_api.register(router, context)  # type: ignore[arg-type]
    response = router.dispatch(
        RpcRequest(id="1", method="narration.publish_pack", params={"plan_id": "nope"})
    )
    assert response.error is not None
