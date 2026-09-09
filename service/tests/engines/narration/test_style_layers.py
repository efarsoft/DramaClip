"""口味层：LLM 自选风格选题；基本功层注入校验。"""

from __future__ import annotations

from typing import Any

from dramaclip.engines.narration import scriptwriter as scriptwriter_lib
from dramaclip.engines.narration import styles
from dramaclip.engines.semantic.llm_client import LlmUnavailable

_TRANSCRIPT = [
    {"start": 1.0, "end": 10.0, "text": "台词一"},
    {"start": 10.0, "end": 30.0, "text": "台词二"},
]


class FakeSelector:
    """返回预设 JSON 或异常，模拟选题调用。"""

    def __init__(self, result: Any) -> None:
        self.result = result
        self.prompts: list[tuple[str, str]] = []

    def chat_json(self, system: str, user: str) -> Any:
        self.prompts.append((system, user))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_selects_valid_style_with_reason() -> None:
    fake = FakeSelector({"style_id": "suspense", "reason": "开局命案，悬疑弧线强"})
    result = styles.select_style_with_reason(fake, _TRANSCRIPT)  # type: ignore[arg-type]
    assert result == ("suspense", "开局命案，悬疑弧线强")
    # 菜单动态来自风格库，且转写节选进入 prompt
    _system, user = fake.prompts[0]
    assert "suspense" in user and "台词转写节选" in user


def test_out_of_library_style_rejected() -> None:
    fake = FakeSelector({"style_id": "not-exist", "reason": "胡选"})
    assert styles.select_style_with_reason(fake, _TRANSCRIPT) is None  # type: ignore[arg-type]


def test_llm_unavailable_returns_none() -> None:
    fake = FakeSelector(LlmUnavailable("timeout"))
    assert styles.select_style_with_reason(fake, _TRANSCRIPT) is None  # type: ignore[arg-type]


def test_empty_transcript_short_circuits(monkeypatch) -> None:
    called = []

    def fail_chat(*_args: Any, **_kwargs: Any) -> None:
        called.append(1)
        raise AssertionError("不应发起 LLM 调用")

    monkeypatch.setattr("dramaclip.engines.narration.styles.LlmClient", fail_chat)
    assert styles.select_style_with_reason(fail_chat, []) is None  # type: ignore[arg-type]
    assert not called


def test_fundamentals_layer_injected_into_system_prompt() -> None:
    system = scriptwriter_lib._SYSTEM_PROMPT
    for keyword in ("解说基本功", "人称二选一", "半句钩", "禁止编造转写外", "前 3 秒抛出"):
        assert keyword in system


def test_fundamentals_precede_style_directives() -> None:
    """基本功在 system prompt（全局），风格 directives 在 user prompt（本次）——分层不混用。"""
    assert "解说风格要求" not in scriptwriter_lib._SYSTEM_PROMPT
