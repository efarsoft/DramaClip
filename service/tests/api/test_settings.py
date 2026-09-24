"""api.settings：get/update（未知键拒绝、写后原地 reload）。"""

from __future__ import annotations

import sqlite3
from typing import Any

from dramaclip.api import settings as settings_api
from dramaclip.transport.rpc import Router, RpcRequest


class Harness:
    def __init__(self, conn: sqlite3.Connection, settings: dict[str, str]) -> None:
        from types import SimpleNamespace

        self.context = SimpleNamespace(conn=conn, settings=settings)
        self.router = Router()
        settings_api.register(self.router, self.context)  # type: ignore[arg-type]

    def rpc(self, method: str, params: dict[str, Any]) -> Any:
        return self.router.dispatch(RpcRequest(id=method, method=method, params=params)).result


def test_update_rejects_unknown_key(memory_db: sqlite3.Connection) -> None:
    harness = Harness(memory_db, {})
    response = harness.router.dispatch(
        RpcRequest(id=1, method="settings.update", params={"values": {"nope.key": "1"}})
    )
    assert response.error is not None and response.error.code == -32001


def test_update_writes_through_to_the_live_snapshot(
    memory_db: sqlite3.Connection,
) -> None:
    """写库之后内存快照必须同步——LLM 端点等热生效靠的就是这一步。"""
    settings = {"llm.base_url": ""}
    harness = Harness(memory_db, settings)

    result = harness.rpc(
        "settings.update", {"values": {"llm.base_url": "https://new.example/v1"}}
    )

    assert result == {"ok": True, "updated": 1}
    assert harness.rpc("settings.get", {})["llm.base_url"] == "https://new.example/v1"
