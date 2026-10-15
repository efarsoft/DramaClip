"""settings 命名空间：get / update（写后原地 reload，W3 起 LLM 端点等热生效）。

LLM 连通性测试不在这里：那能力属于引擎中心的 `engine_configs.test`（业主在弹窗里对着
正在编辑的 base_url/model 按「测试连接」），本命名空间只保管键值对——
按已存配置探测的入口没有界面，留着就是一条协议面上的死方法。
"""

from __future__ import annotations

from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.infra import config
from dramaclip.infra.storage.repos import settings as settings_repo
from dramaclip.transport.rpc import Router, RpcDomainError

_ERR_UNKNOWN_KEY = -32001
_ERR_BAD_VALUE = -32002

#: settings.get 出参里密钥类值的替位；update 认得它=「保持原值」，原样回传不会覆写真 key
MASK_SENTINEL = "••••••••"


#: 密钥类键的后缀判据。按**尾段**认，不按「点分层级」认——
#: `vision.cloud_api_key`（engine_configs 的 image 域镜像写入）尾段是
#: `cloud_api_key`，旧判据 `.api_key` 匹配不到它，实测 settings.get 对它原样回显明文
#: （同期 `llm.api_key` 出掩码）。键名风格混用是既成事实，脱敏判据必须跟着事实走。
_SECRET_SUFFIXES = ("api_key", "token")


def _is_secret(key: str) -> bool:
    tail = key.rsplit(".", 1)[-1]
    return tail.endswith(_SECRET_SUFFIXES)


def register(router: Router, context: AppContext) -> None:
    router.register("settings.get", lambda _params: get(context))
    router.register("settings.update", lambda params: update(context, params))


def get(context: AppContext) -> dict[str, str]:
    """出参脱敏（裁决：密钥不回显）。真值仍留在 context.settings 供内部消费。"""
    return {
        key: (MASK_SENTINEL if _is_secret(key) and value != "" else value)
        for key, value in context.settings.items()
    }


def update(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    values = params.get("values")
    if not isinstance(values, dict) or not values:
        raise RpcDomainError(_ERR_BAD_VALUE, "values 必须为非空对象")
    unknown = [key for key in values if key not in config.DEFAULTS]
    if unknown:
        raise RpcDomainError(_ERR_UNKNOWN_KEY, f"未知设置键: {', '.join(unknown)}")
    kept = 0
    for key, value in values.items():
        if _is_secret(key) and str(value) == MASK_SENTINEL:
            kept += 1  # 前端把掩码原样送回：保持库中真值，不覆写
            continue
        settings_repo.set_value(context.conn, key, str(value))
        context.settings[key] = str(value)
    gateway = getattr(context, "gateway", None)
    if gateway is not None:
        # agent_gateway.* 改动热生效（启停/换端口/token 轮换）；其余键同步是无操作
        gateway.sync(context.settings)
    return {"ok": True, "updated": len(values) - kept}
