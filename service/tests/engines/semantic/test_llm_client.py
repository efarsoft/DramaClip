"""文本 LLM 客户端的唯一构造入口：超时真相与源面门禁。

缺陷背景：`llm.timeout_s` 是界面上能设的端点慢容忍，改造前 ~12 处构造只有 4 处读它，
用户填大之后照旧 60s 读超时，看上去像端点坏了。这里把「一个含义一个读点」升级成门禁。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.semantic import llm_client

_PACKAGE_ROOT = Path(llm_client.__file__).resolve().parent.parent.parent
_FACTORY = "engines/semantic/llm_client.py"
# 键表里的登记不是「读」——config.DEFAULTS 是设置键的真相源，必须允许出现字面键名。
_KEY_TABLE = "infra/config.py"

_CONFIGURED = {"llm.base_url": "https://x/v1", "llm.api_key": "k", "llm.model": "m"}


def _timeout(client: Any) -> float:
    return float(client._timeout_s)  # noqa: SLF001 - 同包测试边界


def test_client_for_honors_llm_timeout_setting() -> None:
    """设置 240 覆盖 60s 下限：这是这条设置存在的唯一理由。"""
    settings = {**_CONFIGURED, "llm.timeout_s": "240"}
    assert _timeout(llm_client.client_for(settings, min_timeout_s=60.0)) == 240.0


def test_client_for_never_drops_below_the_site_floor() -> None:
    """设置比本点下限小不许把成稿的 600s 砍短：成稿实测可达 100s+，砍了就整条报废。"""
    settings = {**_CONFIGURED, "llm.timeout_s": "60"}
    assert _timeout(llm_client.client_for(settings, min_timeout_s=600.0)) == 600.0
    assert _timeout(llm_client.client_for(_CONFIGURED, min_timeout_s=600.0)) == 600.0


def test_client_for_falls_back_when_timeout_setting_unusable() -> None:
    """设置框是自由文本：空/乱填/0/负数一律回落到本点下限，构造本身不许炸。"""
    for value in ("", "abc", "0", "-5"):
        settings = {**_CONFIGURED, "llm.timeout_s": value}
        assert _timeout(llm_client.client_for(settings, min_timeout_s=90.0)) == 90.0, value


def test_client_for_accepts_local_endpoint_without_api_key() -> None:
    """Ollama / LM Studio 没有密钥也算配置齐全——工厂不得偷偷替 `configured` 加 key 条件。"""
    settings = {"llm.base_url": "http://127.0.0.1:11434/v1", "llm.model": "qwen3"}
    client = llm_client.client_for(settings, unconfigured_message="不该抛")
    assert client._config.configured  # noqa: SLF001


def test_client_for_raises_the_callers_message_when_unconfigured() -> None:
    """未配置的文案由各点自己给（界面「引擎」页指引是用户看得懂的那句），工厂原样抛出。"""
    from dramaclip.engines.semantic.llm_client import LlmUnavailable

    with pytest.raises(LlmUnavailable, match="取材角度由模型选定"):
        llm_client.client_for(
            {"llm.base_url": "", "llm.model": ""},
            unconfigured_message="LLM 未配置：取材角度由模型选定，请先在「引擎」页配置文本模型",
        )


def test_llm_timeout_setting_has_a_single_reader() -> None:
    """`llm.timeout_s` 只许在工厂读——第二处读点就是第二处真相，且必然漏掉新调用点。"""
    pattern = re.compile(r"""["']llm\.timeout_s["']""")
    offenders = _scan(pattern, {"infra/config.py"})
    assert offenders == [], "llm.timeout_s 出现多处读点：" + "; ".join(offenders)


def test_llm_client_constructed_only_by_the_factory() -> None:
    """包内除工厂外不得出现 `LlmClient(...)`：绕过工厂的构造天生不吃界面设置。"""
    pattern = re.compile(r"\bLlmClient\(")
    offenders = _scan(pattern, set())
    assert offenders == [], "工厂之外还有 LlmClient 构造点：" + "; ".join(offenders)


def test_client_or_none_degrades_instead_of_raising() -> None:
    """降级调用点要的契约：未配置给 None（它们有兜底产物），配了仍走同一个工厂。"""
    assert llm_client.client_or_none({}) is None
    client = llm_client.client_or_none(_CONFIGURED, min_timeout_s=120.0)
    assert client is not None and _timeout(client) == 120.0


def test_a_real_site_honors_the_setting_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉住原始缺陷本身：界面把 `llm.timeout_s` 调到 900，标题这一跳的真客户端必须拿到 900。

    门禁只保证「读点只有一个」，这条保证「各点真的走工厂」——拦在类级 `chat_json`，
    断言落在真 `LlmClient` 上而不是替身。改造前这里读到的是写死的 120。
    """
    from dramaclip.engines.narration import titles
    from dramaclip.engines.semantic.llm_client import LlmClient

    seen: dict[str, float] = {}

    def _fake_chat(self: LlmClient, _system: str, _user: str, **_k: Any) -> Any:
        seen["timeout_s"] = float(self._timeout_s)  # noqa: SLF001
        return {"titles": ["他一句话，全场安静"], "caption": "发布文案", "tags": ["爽剧"]}

    monkeypatch.setattr(LlmClient, "chat_json", _fake_chat)
    settings = {**_CONFIGURED, "llm.timeout_s": "900"}
    result = titles.generate({"narration_texts": [{"id": "n1", "text": "台词"}]}, settings)
    assert result["titles"][0]["text"] == "他一句话，全场安静"
    assert seen["timeout_s"] == 900.0


def _scan(pattern: re.Pattern[str], allowed: set[str]) -> list[str]:
    hits: list[str] = []
    for source in sorted(_PACKAGE_ROOT.rglob("*.py")):
        relative = source.relative_to(_PACKAGE_ROOT).as_posix()
        if relative == _FACTORY or relative in allowed:
            continue
        for lineno, line in enumerate(
            source.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if pattern.search(line):
                hits.append(f"{relative}:{lineno} {line.strip()}")
    return hits
