"""站点级文本 LLM 替身：把某模块的 `client_for` 换成产出替身客户端的工厂。

构造收进工厂后，模块里不再有 `LlmClient` 这个名字，旧的 `setattr(module, "LlmClient", Fake)`
拦不到构造点——这里补的就是那个 seam。未配置守卫复用真工厂的判定与文案，桩不会和实现漂移；
超时怎么算由 `test_llm_client.py` 直接测真工厂，不在这里重复。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from dramaclip.engines.semantic import llm_client


def patch_client_for(
    monkeypatch: pytest.MonkeyPatch,
    module: Any,
    fake_client: Callable[..., Any],
) -> None:
    """把 `module.client_for(settings, min_timeout_s=..)` 换成返回替身客户端。

    替身客户端沿用旧签名 `(settings, timeout_s=..)`：多数替身不碰第一个参数。
    """

    def _factory(
        settings: dict[str, str],
        *,
        min_timeout_s: float = 60.0,
        unconfigured_message: str | None = None,
    ) -> Any:
        if not llm_client.is_configured(settings):
            raise llm_client.LlmUnavailable(
                unconfigured_message or llm_client.UNCONFIGURED_HINT
            )
        return fake_client(settings, timeout_s=min_timeout_s)

    monkeypatch.setattr(module, "client_for", _factory)
