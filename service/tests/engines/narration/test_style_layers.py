"""口味层：LLM 自选风格选题；基本功层注入校验。"""

from __future__ import annotations

from typing import Any

from dramaclip.engines.narration import scriptwriter as scriptwriter_lib

_TRANSCRIPT = [
    {"start": 1.0, "end": 10.0, "text": "台词一"},
    {"start": 10.0, "end": 30.0, "text": "台词二"},
]


class FakeSelector:
    """返回预设 JSON 或异常，模拟选题调用。"""

    def __init__(self, result: Any) -> None:
        self.result = result
        self.prompts: list[tuple[str, str]] = []

    def chat_json(self, system: str, user: str, temperature: float = 0.3) -> Any:
        self.prompts.append((system, user))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result



def test_fundamentals_layer_injected_into_system_prompt() -> None:
    system = scriptwriter_lib.system_prompt()
    for keyword in ("解说基本功", "人称二选一", "半句钩", "禁止编造转写外", "前 3 秒"):
        assert keyword in system


def test_fundamentals_precede_style_directives() -> None:
    """基本功在 system prompt（全局），风格 directives 在 user prompt（本次）——分层不混用。"""
    assert "解说风格要求" not in scriptwriter_lib.system_prompt()
