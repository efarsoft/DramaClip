"""OpenAI 兼容 LLM 客户端（ADR-005）：stdlib urllib 实现，零第三方依赖。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

_REQUEST_TIMEOUT_S = 60


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


def from_settings(settings: dict[str, str]) -> LlmClient:
    return LlmClient(LlmConfig.from_settings(settings))


class LlmClient:
    def __init__(self, config: LlmConfig, timeout_s: float = _REQUEST_TIMEOUT_S) -> None:
        self._config = config
        self._timeout_s = timeout_s

    @property
    def model(self) -> str:
        return self._config.model

    def chat_json(self, system: str, user: str) -> dict[str, Any] | list[Any]:
        """请求模型返回 JSON 对象/数组；解析失败或 HTTP 错误抛 LlmUnavailable。"""
        if not self._config.configured:
            raise LlmUnavailable("LLM 未配置（需要 base_url 与 model）")
        payload = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.3,
        }
        content = self._post(payload)
        return parse_json_blob(content)

    def ping(self) -> float:
        """连通性探测：max_tokens=1 最小往返，返回耗时秒；异常抛 LlmUnavailable。"""
        start = time.monotonic()
        self._post(
            {
                "model": self._config.model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            }
        )
        return time.monotonic() - start

    def _post(self, payload: dict) -> str:  # type: ignore[type-arg]
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        request = urllib.request.Request(
            f"{self._config.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            raise LlmUnavailable(f"LLM 请求失败: {exc}") from exc
        try:
            return str(body["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmUnavailable(f"LLM 响应格式异常: {exc}") from exc


def parse_json_blob(content: str) -> dict[str, Any] | list[Any]:
    """从模型回复中提取 JSON（容忍 markdown 围栏与前后缀文本）。"""
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
    return candidates
