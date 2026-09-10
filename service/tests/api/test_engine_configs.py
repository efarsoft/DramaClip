"""api.engine_configs：多实例 CRUD、同域单启用、LLM 域镜像 settings。"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from typing import Any

from dramaclip.api import engine_configs as engine_configs_api
from dramaclip.infra.storage.repos import settings as settings_repo
from dramaclip.transport.rpc import Router, RpcRequest


class Harness:
    def __init__(self, conn: sqlite3.Connection, settings: dict[str, str]) -> None:
        self.context = SimpleNamespace(conn=conn, settings=settings)
        self.router = Router()
        engine_configs_api.register(self.router, self.context)  # type: ignore[arg-type]

    def rpc(self, method: str, params: dict[str, Any]) -> Any:
        return self.router.dispatch(RpcRequest(id=method, method=method, params=params)).result

    def error_code(self, method: str, params: dict[str, Any]) -> int | None:
        response = self.router.dispatch(RpcRequest(id=method, method=method, params=params))
        return None if response.error is None else response.error.code


def _create(harness: Harness, name: str = "a", **overrides: str) -> dict[str, Any]:
    params: dict[str, Any] = {
        "domain": "llm",
        "name": name,
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-test-1234",
        "model": "qwen-plus",
    }
    params.update(overrides)
    return harness.rpc("engine_configs.create", params)


def test_create_and_list_by_domain(memory_db: sqlite3.Connection) -> None:
    harness = Harness(memory_db, {})
    created = _create(harness)
    assert created["enabled"] == 0
    # 短 key（≤8 位）全遮蔽，长 key 首尾各保留 4 位
    assert created["api_key_masked"] == "sk-t••••1234"
    long_one = _create(harness, "b", api_key="sk-abcdefghijkl")
    masked = long_one["api_key_masked"]
    assert masked.startswith("sk-a") and masked.endswith("ijkl")
    configs = harness.rpc("engine_configs.list", {"domain": "llm"})["configs"]
    assert [c["id"] for c in configs] == [created["id"], long_one["id"]]


def test_enable_is_single_per_domain(memory_db: sqlite3.Connection) -> None:
    harness = Harness(memory_db, {})
    first = _create(harness, "first")
    second = _create(harness, "second")
    harness.rpc("engine_configs.enable", {"id": first["id"]})
    harness.rpc("engine_configs.enable", {"id": second["id"]})
    listed = harness.rpc("engine_configs.list", {"domain": "llm"})["configs"]
    enabled = {c["name"] for c in listed if c["enabled"] == 1}
    assert enabled == {"second"}


def test_enable_llm_mirrors_settings(memory_db: sqlite3.Connection) -> None:
    settings: dict[str, str] = {}
    harness = Harness(memory_db, settings)
    config = _create(harness)
    harness.rpc("engine_configs.enable", {"id": config["id"]})
    mirrored = settings_repo.get_all(memory_db)
    assert mirrored["llm.base_url"] == "https://api.example.com/v1"
    assert mirrored["llm.model"] == "qwen-plus"


def test_delete_enabled_config_rejected(memory_db: sqlite3.Connection) -> None:
    harness = Harness(memory_db, {})
    config = _create(harness)
    harness.rpc("engine_configs.enable", {"id": config["id"]})
    assert harness.error_code("engine_configs.delete", {"id": config["id"]}) == -32310


def test_update_active_config_resyncs_mirror(memory_db: sqlite3.Connection) -> None:
    settings: dict[str, str] = {}
    harness = Harness(memory_db, settings)
    config = _create(harness)
    harness.rpc("engine_configs.enable", {"id": config["id"]})
    harness.rpc(
        "engine_configs.update",
        {
            "id": config["id"],
            "name": "a",
            "base_url": "https://new.example.com/v1",
            "api_key": "sk-2",
            "model": "qwen-max",
        },
    )
    mirrored = settings_repo.get_all(memory_db)
    assert mirrored["llm.base_url"] == "https://new.example.com/v1"
    assert mirrored["llm.model"] == "qwen-max"


def test_unknown_domain_rejected(memory_db: sqlite3.Connection) -> None:
    harness = Harness(memory_db, {})
    assert harness.error_code("engine_configs.create", {"domain": "nope", "name": "x"}) == -32310
    assert harness.error_code("engine_configs.list", {"domain": "nope"}) == -32310
