"""prompts 命名空间：可编辑 LLM 提示词的查看/保存/重置。

覆盖存 settings 表（键即 SPECS.key），重置 = 删键回默认；
默认值永远在代码里（llm_prompts.SPECS），库里只存改过的。
"""

from __future__ import annotations

from typing import Any

from dramaclip.engines import llm_prompts
from dramaclip.infra.storage.repos import settings as settings_repo
from dramaclip.transport.rpc import Router, RpcDomainError


def register(router: Router, context: Any) -> None:
    def list_prompts(_params: dict[str, Any]) -> dict[str, Any]:
        stored = settings_repo.get_all(context.conn)
        prompts = [
            {
                "key": spec.key,
                "title": spec.title,
                "description": spec.description,
                "default": spec.default,
                "current": stored.get(spec.key) or spec.default,
                "overridden": bool(stored.get(spec.key)),
            }
            for spec in llm_prompts.SPECS
        ]
        return {"prompts": prompts}

    def save(params: dict[str, Any]) -> dict[str, Any]:
        key = str(params.get("key", ""))
        text = str(params.get("text", ""))
        spec = llm_prompts.SPEC_BY_KEY.get(key)
        if spec is None:
            raise RpcDomainError(-32001, f"未知提示词：{key}")
        if not text.strip():
            raise RpcDomainError(-32001, "提示词内容不能为空")
        settings_repo.set_value(context.conn, key, text)
        return {"ok": True}

    def reset(params: dict[str, Any]) -> dict[str, Any]:
        key = str(params.get("key", ""))
        if key not in llm_prompts.SPEC_BY_KEY:
            raise RpcDomainError(-32001, f"未知提示词：{key}")
        settings_repo.delete_value(context.conn, key)
        return {"ok": True}

    router.register("prompts.list", list_prompts)
    router.register("prompts.save", save)
    router.register("prompts.reset", reset)
