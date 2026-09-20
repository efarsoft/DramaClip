"""api.prompts：提示词列表/保存/重置（覆盖存 settings，重置回代码默认）。"""

from __future__ import annotations

from typing import Any

from dramaclip.api import prompts as prompts_api
from dramaclip.engines import llm_prompts
from dramaclip.transport.rpc import Router, RpcRequest

_FLOOR_KEY = "prompt.scriptwriter_fundamentals"


class Harness:
    def __init__(self, conn) -> None:
        from types import SimpleNamespace

        # settings 是运行时快照：出片链路读它，不读库
        self.context = SimpleNamespace(conn=conn, settings={})
        self.router = Router()
        prompts_api.register(self.router, self.context)  # type: ignore[arg-type]

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        request = RpcRequest(id=method, method=method, params=params or {})
        return self.router.dispatch(request).result

    def row(self, key: str) -> dict[str, Any]:
        prompts = self.rpc("prompts.list")["prompts"]
        return next(item for item in prompts if item["key"] == key)


def test_list_returns_all_specs_with_defaults(memory_db) -> None:
    result = Harness(memory_db).rpc("prompts.list")
    assert len(result["prompts"]) == len(llm_prompts.SPECS)
    first = result["prompts"][0]
    assert first["overridden"] is False
    assert first["current"] == first["default"]


def test_every_registered_default_is_readable_text(memory_db) -> None:
    """登记表按名字取常量：改名或取错属性要在这里红，而不是界面上显示空白。"""
    for item in Harness(memory_db).rpc("prompts.list")["prompts"]:
        assert item["default"].strip(), item["key"]


def test_save_overrides_and_reset_restores(memory_db) -> None:
    harness = Harness(memory_db)
    key = llm_prompts.SPECS[0].key
    harness.rpc("prompts.save", {"key": key, "text": "自定义提示词"})
    row = harness.row(key)
    assert row["overridden"] is True and row["current"] == "自定义提示词"

    harness.rpc("prompts.reset", {"key": key})
    row = harness.row(key)
    assert row["overridden"] is False and row["current"] == row["default"]


def test_save_and_reset_reach_the_runtime_snapshot(memory_db) -> None:
    """库改了就等于生效是假话：链路读的是启动快照，两张卡都得跟着动。"""
    harness = Harness(memory_db)
    harness.rpc("prompts.save", {"key": _FLOOR_KEY, "text": "自定义底线"})
    assert llm_prompts.system_override(harness.context.settings, _FLOOR_KEY) == "自定义底线"

    harness.rpc("prompts.reset", {"key": _FLOOR_KEY})
    assert llm_prompts.system_override(harness.context.settings, _FLOOR_KEY) is None


def test_saving_the_default_text_verbatim_is_not_an_override(memory_db) -> None:
    """「填回默认内容」再保存不该让卡片永远挂着「已修改」。"""
    harness = Harness(memory_db)
    default = harness.row(_FLOOR_KEY)["default"]
    harness.rpc("prompts.save", {"key": _FLOOR_KEY, "text": default})
    row = harness.row(_FLOOR_KEY)
    assert row["overridden"] is False and row["current"] == default
    assert _FLOOR_KEY not in harness.context.settings


def test_structure_and_floor_cards_own_disjoint_spans(memory_db) -> None:
    """结构卡与基本功卡不能互相包含：重叠时改一张卡的效果在另一张上看不出来。"""
    harness = Harness(memory_db)
    structure = harness.row("prompt.scriptwriter_system")["default"]
    copy = harness.row("prompt.copywriter_system")["default"]
    floor = harness.row(_FLOOR_KEY)["default"]
    assert "【解说基本功" not in structure
    assert "【解说基本功" not in copy
    assert "【解说基本功" in floor


def test_save_rejects_unknown_key_and_empty_text(memory_db) -> None:
    harness = Harness(memory_db)
    bad = {"key": "nope", "text": "x"}
    for params in (bad, {"key": llm_prompts.SPECS[0].key, "text": "  "}):
        request = RpcRequest(id=1, method="prompts.save", params=params)
        response = harness.router.dispatch(request)
        assert response.error is not None and response.error.code == -32001


def test_save_rejects_an_absurdly_long_prompt(memory_db) -> None:
    """提示词会原样进每一次 LLM 往返：不设上限等于让人能一键把上下文预算撑爆。"""
    harness = Harness(memory_db)
    too_long = "字" * (llm_prompts.MAX_PROMPT_CHARS + 1)
    request = RpcRequest(
        id=1, method="prompts.save", params={"key": _FLOOR_KEY, "text": too_long}
    )
    response = harness.router.dispatch(request)
    assert response.error is not None and response.error.code == -32002
    assert _FLOOR_KEY not in harness.context.settings
