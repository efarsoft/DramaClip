"""api.prompts：提示词列表/保存/重置（覆盖存 settings，重置回代码默认）。"""

from __future__ import annotations

from typing import Any

from dramaclip.api import prompts as prompts_api
from dramaclip.engines import llm_prompts
from dramaclip.infra.storage.repos import settings as settings_repo
from dramaclip.transport.rpc import Router, RpcRequest


class Harness:
    def __init__(self, conn) -> None:
        self.context = type("C", (), {"conn": conn})()
        self.router = Router()
        prompts_api.register(self.router, self.context)

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        return self.router.dispatch(RpcRequest(id=method, method=method, params=params or {})).result


def test_list_returns_all_specs_with_defaults(memory_db) -> None:
    result = Harness(memory_db).rpc("prompts.list")
    assert len(result["prompts"]) == len(llm_prompts.SPECS)
    first = result["prompts"][0]
    assert first["overridden"] is False
    assert first["current"] == first["default"]


def test_save_overrides_and_reset_restores(memory_db) -> None:
    harness = Harness(memory_db)
    key = llm_prompts.SPECS[0].key
    harness.rpc("prompts.save", {"key": key, "text": "自定义提示词"})
    listing = Harness(memory_db).rpc("prompts.list")
    row = next(p for p in listing["prompts"] if p["key"] == key)
    assert row["overridden"] is True and row["current"] == "自定义提示词"
    # 引擎侧取覆盖：settings 里有值
    stored = settings_repo.get_all(memory_db)
    assert llm_prompts.system_override(stored, key) == "自定义提示词"

    harness.rpc("prompts.reset", {"key": key})
    listing = Harness(memory_db).rpc("prompts.list")
    row = next(p for p in listing["prompts"] if p["key"] == key)
    assert row["overridden"] is False and row["current"] == row["default"]


def test_save_rejects_unknown_key_and_empty_text(memory_db) -> None:
    harness = Harness(memory_db)
    for params in ({"key": "nope", "text": "x"}, {"key": llm_prompts.SPECS[0].key, "text": "  "}):
        response = harness.router.dispatch(RpcRequest(id=1, method="prompts.save", params=params))
        assert response.error is not None and response.error.code == -32001
