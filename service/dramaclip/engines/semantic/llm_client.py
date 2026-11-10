"""OpenAI 兼容 LLM 客户端（ADR-005）：stdlib urllib 实现，零第三方依赖。"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from dramaclip.engines.semantic import llm_budget

_REQUEST_TIMEOUT_S = 60
_NET_RETRY_BACKOFF = (5.0, 15.0)  # 网络类失败短退避：抖动型故障两轮内多数自愈
_429_BACKOFF = [30, 60, 120]

logger = logging.getLogger(__name__)


class _StreamUnavailable(Exception):
    """网关不支持 SSE 流（返回普通 JSON）或流全程无 content 帧的回退标记。"""


class LlmUnavailable(Exception):
    """LLM 未配置或不可达（调用方降级）。"""


class LlmContentBlocked(LlmUnavailable):
    """内容审核拒绝（区别于网络/限流/鉴权）：调用方可针对性降级而非烧重试。"""


#: 云厂商内容审核拒绝的典型标识（错误体/消息关键词，小写匹配）
_CONTENT_BLOCKED_MARKERS = (
    "datainspectionfailed",
    "risk control",
    "riskcontrol",
    "content inspection",
    "content filter",
    "content management",
    "sensitive content",
    "内容审核",
    "敏感内容",
)


def is_content_blocked(message: str) -> bool:
    """错误文本是否命中内容审核类拒绝——调用方据此走降级而非重试。"""
    lowered = message.lower()
    return any(marker in lowered for marker in _CONTENT_BLOCKED_MARKERS)


def _classify_http_error(exc: urllib.error.HTTPError) -> LlmUnavailable:
    """非 429 HTTP 错误分类：审核拒绝 → LlmContentBlocked，其余 → LlmUnavailable。"""
    try:
        detail = exc.read().decode("utf-8", "replace")[:300]
    except OSError:
        detail = str(exc)
    if is_content_blocked(detail):
        return LlmContentBlocked(f"LLM 内容审核拒绝: {detail}")
    return LlmUnavailable(f"LLM 请求失败: {exc.code} {detail}")


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
        # 流式优先（第一梯队②）：SSE 边生成边读——socket 超时语义从「整包最长
        # 等待」变成「两行之间最长等待」，长思考/长文案的静默连接不再被网关
        # 从中间掐断（urlopen timeout 在两次 read 间自动重置）。空产物自动
        # 回退非流式：不支持 stream 的网关返回普通 JSON，旧路径原样兼容。
        try:
            return self._stream_chat(headers, payload)
        except _StreamUnavailable:
            body = self._urlopen_with_429_backoff(
                headers, json.dumps(payload).encode("utf-8")
            )
            try:
                return str(body["choices"][0]["message"]["content"])
            except (KeyError, IndexError, TypeError) as exc:
                raise LlmUnavailable(f"LLM 响应格式异常: {exc}") from exc

    def _stream_chat(
        self, headers: dict[str, str], payload: dict[str, Any]
    ) -> str:
        """SSE 流式聚合（429 长退避 + 网络短退避与非流式同款分类）。"""
        net_failures = 0
        rate_failures = 0
        wait: float = 0.0
        while True:
            req = urllib.request.Request(
                f"{self._config.base_url}/chat/completions",
                data=json.dumps({**payload, "stream": True}).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(
                    req, timeout=llm_budget.check_and_timeout(self._timeout_s)
                ) as resp:
                    return self._read_sse(resp)
            except urllib.error.HTTPError as exc:
                if exc.code != 429:
                    raise _classify_http_error(exc) from exc
                rate_failures += 1
                if rate_failures >= len(_429_BACKOFF):
                    raise LlmUnavailable("LLM 请求失败: 429 重试耗尽") from exc
                wait = _429_BACKOFF[rate_failures - 1]
                logger.warning(
                    "LLM 429 限流，%ds 后重试 (%d/%d)",
                    wait, rate_failures, len(_429_BACKOFF),
                )
                time.sleep(wait)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                net_failures += 1
                if net_failures > len(_NET_RETRY_BACKOFF):
                    raise LlmUnavailable(f"LLM 请求失败: {exc}") from exc
                wait = _NET_RETRY_BACKOFF[net_failures - 1]
                logger.warning(
                    "LLM 网络类失败（%s），%.0fs 后重试 (%d/%d)",
                    exc, wait, net_failures, len(_NET_RETRY_BACKOFF),
                )
                time.sleep(wait)
            except _StreamUnavailable:
                raise  # 网关不支持流：交给 _post 回退非流式，不计失败账

    def _read_sse(self, resp: Any) -> str:
        """消费 SSE 响应体，聚合 delta.content；空产物抛回退标记。"""
        pieces: list[str] = []
        saw_data = False
        for raw_line in resp:
            line = raw_line.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data:
                continue
            if data == "[DONE]":
                break
            saw_data = True
            try:
                obj = json.loads(data)
            except ValueError:
                continue  # 坏行跳过：SSE 心跳/注释行不是致命错误
            if isinstance(obj.get("error"), dict):
                raise LlmUnavailable(
                    f"LLM 流式响应报错: {obj['error'].get('message') or obj['error']}"
                )
            try:
                delta = obj["choices"][0]["delta"].get("content")
            except (KeyError, IndexError, TypeError):
                continue  # 无 delta 的帧（角色帧/用量帧/keep-alive）跳过
            if delta:
                pieces.append(str(delta))
        if not pieces:
            # 全程无 content 帧两种可能：网关忽略 stream 返回了普通 JSON（首块
            # 不带 data: 前缀），或确实空回答——都回退非流式路径裁决。
            if not saw_data:
                raise _StreamUnavailable()
            raise _StreamUnavailable()
        return "".join(pieces)

    def _urlopen_with_429_backoff(
        self, headers: dict[str, str], data: bytes
    ) -> dict[str, Any]:
        """非流式底座（网络类失败短退避重试后才认输——一次抖动不该炸整条任务）。

        非 429 的 HTTP 错误（鉴权/参数/模型名）仍立即上抛：那类重试没有意义。
        """
        net_failures = 0
        rate_failures = 0
        wait: float = 0.0
        while True:
            req = urllib.request.Request(
                f"{self._config.base_url}/chat/completions",
                data=data,
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(
                    req, timeout=llm_budget.check_and_timeout(self._timeout_s)
                ) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
                    return dict(raw)
            except urllib.error.HTTPError as exc:
                if exc.code != 429:
                    raise LlmUnavailable(f"LLM 请求失败: {exc}") from exc
                rate_failures += 1
                if rate_failures >= len(_429_BACKOFF):
                    raise LlmUnavailable("LLM 请求失败: 429 重试耗尽") from exc
                wait = _429_BACKOFF[rate_failures - 1]
                logger.warning(
                    "LLM 429 限流，%ds 后重试 (%d/%d)",
                    wait, rate_failures, len(_429_BACKOFF),
                )
                time.sleep(wait)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                net_failures += 1
                if net_failures > len(_NET_RETRY_BACKOFF):
                    raise LlmUnavailable(f"LLM 请求失败: {exc}") from exc
                wait = _NET_RETRY_BACKOFF[net_failures - 1]
                logger.warning(
                    "LLM 网络类失败（%s），%.0fs 后重试 (%d/%d)",
                    exc, wait, net_failures, len(_NET_RETRY_BACKOFF),
                )
                time.sleep(wait)


def _strip_reasoning_blocks(text: str) -> str:
    """reasoning 模型把推理过程包在 <think> 块里输出：块内常含花括号样本，
    嵌入式 JSON 提取会捞到推理残渣而非正文——解析前整块清除（含未闭合块）。"""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*\Z", "", text, flags=re.DOTALL)
    return text.replace("</think>", "")


def parse_json_blob(content: str) -> dict[str, Any] | list[Any]:
    text = _strip_reasoning_blocks(content.strip())
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
