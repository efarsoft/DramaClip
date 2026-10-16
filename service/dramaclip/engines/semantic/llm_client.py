"""OpenAI 兼容 LLM 客户端（ADR-005）：stdlib urllib 实现，零第三方依赖。"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

_REQUEST_TIMEOUT_S = 60
_429_BACKOFF = [30, 60, 120]

logger = logging.getLogger(__name__)


class LlmUnavailable(Exception):
    """LLM 未配置或不可达（调用方降级）。"""


@dataclass(frozen=True)
class LlmConfig:
    base_url: str
    api_key: str
    model: str

    @classmethod
    def from_settings(cls, settings: dict[str, str]) -> LlmConfig:
        return cls(
            base_url=str(settings.get("llm.base_url", "")).strip().rstrip("/"),
            api_key=str(settings.get("llm.api_key", "")).strip(),
            model=str(settings.get("llm.model", "")).strip(),
        )

    @property
    def configured(self) -> bool:
        return bool(self.base_url) and bool(self.model)


UNCONFIGURED_HINT = "LLM 未配置（需要 base_url 与 model）"
# 指引句只有一个家：各调用点自带文案时，六句话有六种句式，改一处漏五处。
_UNCONFIGURED_COPY = "LLM 未配置：{site}由模型产出，请先在「引擎」页配置文本模型"


def is_configured(settings: dict[str, str]) -> bool:
    """降级调用点用的判定：它们返回兜底值而不是抛，所以判定必须留在自己手里。"""
    return LlmConfig.from_settings(settings).configured


def client_for(
    settings: dict[str, str],
    *,
    min_timeout_s: float = _REQUEST_TIMEOUT_S,
    site: str | None = None,
) -> LlmClient:
    """文本 LLM 客户端的唯一构造入口，未配置即抛 `LlmUnavailable`。

    `site` 是这件产物的名字（如「取材角度」），报给用户时说明少了它什么产出不了；
    上游已用 `is_configured` 拦住的防御性调用可以不填。

    超时 = `max(llm.timeout_s, min_timeout_s)`：界面那个键是端点慢容忍，`min_timeout_s`
    是本调用点自量的最短读完时间，两边只能抬高、谁也不许压低别人。`llm.timeout_s`
    **只在本函数读**，第二处读点就是第二处真相。
    """
    config = LlmConfig.from_settings(settings)
    if not config.configured:
        raise LlmUnavailable(
            _UNCONFIGURED_COPY.format(site=site) if site else UNCONFIGURED_HINT
        )
    raw = str(settings.get("llm.timeout_s") or "").strip()
    try:
        # 0/负数这类误填也按下限：造一个立刻超时的客户端比不造更难查。
        configured_timeout = float(raw) if raw else min_timeout_s
    except ValueError:
        logger.warning("llm.timeout_s=%r 不是数字，按本点下限 %ss", raw, min_timeout_s)
        configured_timeout = min_timeout_s
    return LlmClient(config, timeout_s=max(min_timeout_s, configured_timeout))


def client_or_none(
    settings: dict[str, str], *, min_timeout_s: float = _REQUEST_TIMEOUT_S
) -> LlmClient | None:
    """降级调用点的构造入口：未配置返回 None，而不是抛（它们有兜底产物）。"""
    if not is_configured(settings):
        return None
    return client_for(settings, min_timeout_s=min_timeout_s)


class LlmClient:
    def __init__(self, config: LlmConfig, timeout_s: float = _REQUEST_TIMEOUT_S) -> None:
        self._config = config
        self._timeout_s = timeout_s

    @property
    def model(self) -> str:
        return self._config.model

    def chat_json(
        self, system: str, user: str, temperature: float | None = None
    ) -> dict[str, Any] | list[Any]:
        if not self._config.configured:
            raise LlmUnavailable(UNCONFIGURED_HINT)
        payload = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # 创意链路（剧本/逐槽填词/标题/金句）走 0.75，其余默认 0.3 保稳。
            "temperature": temperature if temperature is not None else 0.3,
        }
        content = self._post(payload)
        return parse_json_blob(content)

    def ping(self) -> float:
        start = time.monotonic()
        self._post({
            "model": self._config.model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        })
        return time.monotonic() - start

    def _post(self, payload: dict) -> str:  # type: ignore[type-arg]
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        body = self._urlopen_with_429_backoff(headers, json.dumps(payload).encode("utf-8"))
        try:
            return str(body["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmUnavailable(f"LLM 响应格式异常: {exc}") from exc

    def _urlopen_with_429_backoff(
        self, headers: dict[str, str], data: bytes
    ) -> dict[str, Any]:
        for attempt, wait in enumerate(_429_BACKOFF):
            req = urllib.request.Request(
                f"{self._config.base_url}/chat/completions",
                data=data,
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
                    return dict(raw)
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < len(_429_BACKOFF) - 1:
                    logger.warning(
                        "LLM 429 限流，%ds 后重试 (%d/%d)", wait, attempt + 1, len(_429_BACKOFF)
                    )
                    time.sleep(wait)
                    continue
                raise LlmUnavailable(f"LLM 请求失败: {exc}") from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                raise LlmUnavailable(f"LLM 请求失败: {exc}") from exc
        raise LlmUnavailable("LLM 请求失败: 重试耗尽")


def parse_json_blob(content: str) -> dict[str, Any] | list[Any]:
    text = content.strip()
    for candidate in _json_candidates(text):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, (dict, list)):
            return parsed
    raise LlmUnavailable("LLM 未返回有效 JSON")


def _json_candidates(text: str) -> list[str]:
    candidates = [text]
    fence_start = text.find("```")
    if fence_start >= 0:
        body = text[fence_start:].lstrip("`")
        if body[:4].lower() == "json":
            body = body[4:]
        fence_end = body.find("```")
        if fence_end >= 0:
            candidates.append(body[:fence_end].strip())
    first_obj = text.find("{")
    first_arr = text.find("[")
    starts = [pos for pos in (first_obj, first_arr) if pos >= 0]
    if starts:
        start = min(starts)
        closer = "}" if text[start] == "{" else "]"
        end = text.rfind(closer)
        if end > start:
            candidates.append(text[start : end + 1])
    # 轻修复只加一条「去尾逗号」：`,}` / `,]` 是 LLM 的头号手滑，删掉就能解析。
    # 不做括号配平/补引号——那是替模型重写响应。原候选在前，严格 JSON 优先。
    candidates.extend(
        stripped
        for stripped in (_strip_trailing_commas(c) for c in list(candidates))
        if stripped not in candidates
    )
    return candidates


def _strip_trailing_commas(text: str) -> str:
    """删除紧邻 `}`/`]` 之前的逗号（跳过其间空白）。字符串字面量内的逗号不动。"""
    out: list[str] = []
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            out.append(char)
            continue
        if in_string:
            if char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            out.append(char)
            continue
        if char == '"':
            in_string = True
            out.append(char)
            continue
        if char == ",":
            rest = text[index + 1 :].lstrip()
            if rest[:1] in ("}", "]"):
                continue  # 尾逗号：丢弃
        out.append(char)
    return "".join(out)
