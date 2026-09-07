"""settings 命名空间：get / update / test_llm（写后原地 reload，W3 起 LLM 端点等热生效）。"""

from __future__ import annotations

from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.engines.semantic.llm_client import LlmConfig, LlmUnavailable, from_settings
from dramaclip.infra import config
from dramaclip.infra.storage.repos import settings as settings_repo
from dramaclip.transport.rpc import Router, RpcDomainError

_ERR_UNKNOWN_KEY = -32001
_ERR_BAD_VALUE = -32002
_ERR_LLM_NOT_CONFIGURED = -32003
_ERR_LLM_UNREACHABLE = -32004


def register(router: Router, context: AppContext) -> None:
    router.register("settings.get", lambda _params: get(context))
    router.register("settings.update", lambda params: update(context, params))
    router.register("settings.test_llm", lambda _params: test_llm(context))


def get(context: AppContext) -> dict[str, str]:
    return dict(context.settings)


def update(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    values = params.get("values")
    if not isinstance(values, dict) or not values:
        raise RpcDomainError(_ERR_BAD_VALUE, "values 必须为非空对象")
    unknown = [key for key in values if key not in config.DEFAULTS]
    if unknown:
        raise RpcDomainError(_ERR_UNKNOWN_KEY, f"未知设置键: {', '.join(unknown)}")
    for key, value in values.items():
        settings_repo.set_value(context.conn, key, str(value))
        context.settings[key] = str(value)
    return {"ok": True, "updated": len(values)}


def test_llm(context: AppContext) -> dict[str, Any]:
    """按当前已保存配置探测 LLM 连通性（前端提示先保存再测试）。"""
    if not LlmConfig.from_settings(context.settings).configured:
        raise RpcDomainError(_ERR_LLM_NOT_CONFIGURED, "LLM 未配置：请先保存 base_url 与 model")
    try:
        latency_s = from_settings(context.settings).ping()
    except LlmUnavailable as exc:
        raise RpcDomainError(_ERR_LLM_UNREACHABLE, str(exc)) from exc
    return {
        "ok": True,
        "latency_ms": round(latency_s * 1000),
        "model": str(context.settings.get("llm.model", "")),
    }
