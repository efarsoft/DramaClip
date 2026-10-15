"""api.settings：get/update（未知键拒绝、写后原地 reload）。"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from dramaclip.api import settings as settings_api
from dramaclip.infra.storage.repos import settings as settings_repo
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


def test_get_replaces_secret_values_with_the_sentinel(memory_db: sqlite3.Connection) -> None:
    """密钥类键（*.api_key / *.token）出参只给替位；空值不涂掩码，UI 仍是干净的空框。"""
    harness = Harness(
        memory_db,
        {
            "llm.api_key": "sk-real-secret",
            "agent_gateway.token": "tok-real",
            "asr.api_key": "",
            "llm.base_url": "https://api.example/v1",
        },
    )
    projected = harness.rpc("settings.get", {})

    assert projected["llm.api_key"] == settings_api.MASK_SENTINEL
    assert projected["agent_gateway.token"] == settings_api.MASK_SENTINEL
    assert projected["asr.api_key"] == ""
    assert projected["llm.base_url"] == "https://api.example/v1"
    assert "sk-real-secret" not in json.dumps(projected)
    # 脱敏是投影不是改写：内存快照仍持真值，消费方（LLM/TTS 客户端）照常可用
    assert harness.context.settings["llm.api_key"] == "sk-real-secret"  # type: ignore[attr-defined]


def test_update_treats_the_sentinel_as_keep_current(
    memory_db: sqlite3.Connection,
) -> None:
    """UI 把掩码原样送回 = 保持库中现值；计数只算真写下的键，避免「改了什么」虚报。"""
    harness = Harness(memory_db, {"llm.api_key": "sk-real-secret", "llm.model": "old"})
    settings_repo.set_value(memory_db, "llm.api_key", "sk-real-secret")

    result = harness.rpc(
        "settings.update",
        {"values": {"llm.api_key": settings_api.MASK_SENTINEL, "llm.model": "qwen-max"}},
    )

    assert result == {"ok": True, "updated": 1}
    assert settings_repo.get_all(memory_db)["llm.api_key"] == "sk-real-secret"
    assert harness.context.settings["llm.api_key"] == "sk-real-secret"  # type: ignore[attr-defined]
