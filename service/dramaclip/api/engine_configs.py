"""engine_configs 命名空间：云端/服务端点配置的多实例管理（单启用）。
"""

from __future__ import annotations

from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.engines.semantic.llm_client import LlmClient, LlmConfig, LlmUnavailable
from dramaclip.infra.storage.repos import engine_configs as configs_repo
from dramaclip.transport.rpc import Router, RpcDomainError

_ERR_BAD = -32310
_ERR_NOT_FOUND = -32311

_DOMAINS = ("llm", "tts_cloud", "asr_cloud", "image", "video")


def register(router: Router, context: AppContext) -> None:
    router.register("engine_configs.list", lambda params: _list(context, params))
    router.register("engine_configs.create", lambda params: create(context, params))
    router.register("engine_configs.update", lambda params: update(context, params))
    router.register("engine_configs.delete", lambda params: delete(context, params))
    router.register("engine_configs.enable", lambda params: enable(context, params))
    router.register("engine_configs.test", lambda params: test(context, params))


def _list(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    domain = str(params.get("domain", ""))
    _assert_domain(domain)
    return {"configs": configs_repo.list_by_domain(context.conn, domain)}


def create(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    domain, name, base_url, model = _fields(params)
    api_key = str(params.get("api_key", ""))
    config = configs_repo.create(context.conn, domain, name, base_url, api_key, model)
    if params.get("enable"):
        _enable(context, domain, str(config["id"]))
        refreshed = configs_repo.get(context.conn, str(config["id"]))
        if refreshed is not None:
            config = refreshed
    return config


def update(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    config_id = str(params.get("id", ""))
    name = str(params.get("name", "")).strip()
    if name == "":
        raise RpcDomainError(_ERR_BAD, "名称不能为空")
    existing = configs_repo.get(context.conn, config_id)
    if existing is None:
        raise RpcDomainError(_ERR_NOT_FOUND, f"配置不存在: {config_id}")
    configs_repo.update(
        context.conn,
        config_id,
        name=name,
        base_url=str(params.get("base_url", "")),
        api_key=str(params.get("api_key", "")),
        model=str(params.get("model", "")),
    )
    updated = configs_repo.get(context.conn, config_id)
    assert updated is not None, "更新后配置丢失"
    # 启用中的配置被编辑：镜像同步到 settings，保证即时生效
    if updated["enabled"]:
        _mirror_llm_settings(context, updated)
    return updated


def delete(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    config_id = str(params.get("id", ""))
    existing = configs_repo.get(context.conn, config_id)
    if existing is None:
        raise RpcDomainError(_ERR_NOT_FOUND, f"配置不存在: {config_id}")
    if existing["enabled"]:
        raise RpcDomainError(_ERR_BAD, "启用中的配置不能删除，请先启用其他配置")
    configs_repo.delete(context.conn, config_id)
    return {"ok": True}


def enable(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    config_id = str(params.get("id", ""))
    existing = configs_repo.get(context.conn, config_id)
    if existing is None:
        raise RpcDomainError(_ERR_NOT_FOUND, f"配置不存在: {config_id}")
    configs_repo.set_enabled(context.conn, str(existing["domain"]), config_id)
    if str(existing["domain"]) == "llm":
        _mirror_llm_settings(context, existing)
    enabled = configs_repo.get(context.conn, config_id)
    assert enabled is not None
    return enabled


def test(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """连通性测试：构造临时客户端发起最小请求。"""
    base_url = str(params.get("base_url", ""))
    api_key = str(params.get("api_key", ""))
    model = str(params.get("model", ""))
    if base_url == "" or model == "":
        raise RpcDomainError(_ERR_BAD, "base_url 与 model 不能为空")
    try:
        client = LlmClient(
            LlmConfig(base_url=base_url, api_key=api_key, model=model),
            timeout_s=30.0,
        )
        latency = client.ping()
    except LlmUnavailable as exc:
        return {"ok": False, "latency_s": None, "error": str(exc)}
    return {"ok": True, "latency_s": round(latency, 2), "error": None}


def _fields(params: dict[str, Any]) -> tuple[str, str, str, str]:
    domain = str(params.get("domain", "")).strip()
    name = str(params.get("name", "")).strip()
    base_url = str(params.get("base_url", "")).strip().rstrip("/")
    model = str(params.get("model", "")).strip()
    if domain not in _DOMAINS:
        raise RpcDomainError(_ERR_BAD, f"不支持的能力域: {domain}")
    if name == "":
        raise RpcDomainError(_ERR_BAD, "名称不能为空")
    return domain, name, base_url, model


def _assert_domain(domain: str) -> None:
    if domain not in _DOMAINS:
        raise RpcDomainError(_ERR_BAD, f"不支持的能力域: {domain}")


def _enable(context: AppContext, domain: str, config_id: str) -> None:
    configs_repo.set_enabled(context.conn, domain, config_id)
    if domain == "llm":
        updated = configs_repo.get(context.conn, config_id)
        if updated is not None:
            _mirror_llm_settings(context, updated)


def _mirror_llm_settings(context: AppContext, config: dict[str, Any]) -> None:
    """启用中的 LLM 配置镜像到 llm.* 三键——既有消费方零改动。"""
    from dramaclip.infra.storage.repos import settings as settings_repo

    mirror = {
        "llm.base_url": str(config["base_url"]),
        "llm.api_key": str(config["api_key"]),
        "llm.model": str(config["model"]),
    }
    for key, value in mirror.items():
        settings_repo.set_value(context.conn, key, value)
        context.settings[key] = value
