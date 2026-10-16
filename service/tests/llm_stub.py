"""站点级文本 LLM 替身：把某模块的 `client_for` 换成产出替身客户端的工厂。

构造收进工厂后，模块里不再有 `LlmClient` 这个名字，旧的 `setattr(module, "LlmClient", Fake)`
拦不到构造点——这里补的就是那个 seam；未配置守卫由真工厂跑一遍，桩不会和实现漂移。
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
    """把 `module.client_for(settings, min_timeout_s=.., site=..)` 换成返回替身客户端。

    未配置守卫交给真工厂跑一遍再丢弃结果：桩里手写判定与文案必然和实现漂移。
    构造本身不发请求，白跑一次只多造一个没人用的对象。
    """

    def _factory(
        settings: dict[str, str],
        *,
        min_timeout_s: float = 60.0,
        site: str | None = None,
    ) -> Any:
        llm_client.client_for(settings, min_timeout_s=min_timeout_s, site=site)
        return fake_client(settings, timeout_s=min_timeout_s)

    monkeypatch.setattr(module, "client_for", _factory)
