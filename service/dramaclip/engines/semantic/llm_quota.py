"""LLM 额度预检（第二梯队①）：批量出片前查中转站余额，fail-open 不装死。

New API 系中转站普遍支持 ``GET /dashboard/billing/subscription``（OpenAI 兼容
余额查询端点）。批量出片前 3s 超时探一次：
- 余额充足（``hard_limit_usd > 0.5``）→ 放行；
- 余额不足 → 拦下整批（比跑到第 7 集才碰一墙 429 好得多）；
- 端点不支持 / 超时 / 任何异常 → **fail-open 放行**（预检是增强不是义务，
  不能因为中转站不支持余额查询就不让出片）。

结果缓存 60s（批量提交连点不重复探测），永不外露余额数字（只报够/不够）。
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

from dramaclip.engines.semantic.llm_client import LlmConfig

logger = logging.getLogger(__name__)

_CACHE: dict[str, tuple[float, str]] = {}  # base_url → (monotonic, verdict)
_CACHE_TTL_S = 60.0
_PROBE_TIMEOUT_S = 3.0
_MIN_BALANCE_USD = 0.5  # 低于此值判「不够」——一次文案调用的典型费用量级

#: 预检结果枚举（对外只报这三态，余额数字不离开本模块）
OK = "ok"
EXHAUSTED = "exhausted"
SKIPPED = "skipped"  # 不支持/超时/异常 → fail-open


def probe_quota(config: LlmConfig) -> str:
    """探测中转站余额（OK/EXHAUSTED/SKIPPED），60s 缓存，异常一律 fail-open。"""
    now = time.monotonic()
    cached = _CACHE.get(config.base_url)
    if cached is not None and now - cached[0] < _CACHE_TTL_S:
        return cached[1]

    verdict = _probe_once(config)
    _CACHE[config.base_url] = (now, verdict)
    return verdict


def _probe_once(config: LlmConfig) -> str:
    base = config.base_url.rstrip("/")
    # /v1/chat/completions → /v1/dashboard/billing/subscription；无 /v1 的裸域名
    # 也试同路径（多数 New API 系在 /v1 下暴露）
    probe_url = f"{base}/dashboard/billing/subscription"
    req = urllib.request.Request(
        probe_url,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=_PROBE_TIMEOUT_S) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return SKIPPED  # 不支持余额查询的端点：预检是增强不是义务
    try:
        limit = float(body.get("hard_limit_usd", 0))
    except (TypeError, ValueError):
        return SKIPPED
    if limit < _MIN_BALANCE_USD:
        logger.warning("LLM 额度预检：余额不足（limit=%.2f USD），建议充值", limit)
        return EXHAUSTED
    return OK


def precheck_or_warn(config: LlmConfig, warn: Any) -> bool:
    """预检并留痕；返回 True=可继续（OK 或 SKIPPED），False=余额不足应拦。"""
    verdict = probe_quota(config)
    if verdict == EXHAUSTED:
        warn(
            "LLM 额度预检：余额不足——批量出片可能中途碰墙 "
            "（充值后重跑；预检为 fail-open，此提示不拦出片）"
        )
        return True  # fail-open：只警告不拦（业主裁决点：拦还是警告）
    return True

