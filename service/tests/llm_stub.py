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
        retry: bool = True,
    ) -> Any:
        llm_client.client_for(settings, min_timeout_s=min_timeout_s, site=site, retry=retry)
        return fake_client(settings, timeout_s=min_timeout_s)

    monkeypatch.setattr(module, "client_for", _factory)


class FakeLlm:
    """chat_json 网关替身基类：真引擎契约（签名同 LlmClient.chat_json，含
    ``temperature: float | None``）+ 调用记账（calls）。

    固定应答用 ``reply``；要抛错用 ``error``；场景差异（按 system 分层产出、
    首轮失败重试等）子类覆写 ``produce``。
    """

    def __init__(
        self, reply: Any = None, error: Exception | None = None
    ) -> None:
        self.reply = reply
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def chat_json(
        self, system: str, user: str, temperature: float | None = None
    ) -> Any:
        self.calls.append((system, user))
        if self.error is not None:
            raise self.error
        return self.produce(system, user)

    def produce(self, system: str, user: str) -> Any:
        return self.reply
