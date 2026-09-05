"""models 命名空间：list / download / scan（本地导入）/ delete。"""

from __future__ import annotations

import shutil
import threading
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.infra.model_manager import downloader, registry
from dramaclip.transport.rpc import Router, RpcDomainError

_ERR_MODEL_NOT_FOUND = -32010
_ERR_MODEL_STATE = -32011


def register(router: Router, context: AppContext) -> None:
    router.register("models.list", lambda _params: list_models(context))
    router.register("models.download", lambda params: download(context, params))
    router.register("models.scan_local", lambda params: scan_local(context))
    router.register("models.delete", lambda params: delete(context, params))


def list_models(context: AppContext) -> list[dict[str, Any]]:
    """清单 + 状态（内置清单 ∪ models/ 目录手动放置的发现项）。"""
    models_dir = context.work_dir.parent.parent / "models"
    return registry.list_models(models_dir)


def download(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    model_id = str(params.get("model_id", ""))
    spec = downloader.spec_by_id(model_id)
    if spec is None:
        raise RpcDomainError(_ERR_MODEL_NOT_FOUND, f"未知模型: {model_id}")
    models_dir = context.work_dir.parent.parent / "models"
    if registry.find(spec, models_dir) is not None:
        raise RpcDomainError(_ERR_MODEL_STATE, f"{spec.name} 已安装")
    job_id = context.job_store.create("model_download", ref_id=model_id)
    cancel_event = threading.Event()
    context.cancel_events[job_id] = cancel_event
    done_event = threading.Event()

    def _finalize() -> None:
        context.cancel_events.pop(job_id, None)
        status = context.job_store.get(job_id)
        if status is not None and status["status"] == "running":
            context.job_store.mark_completed(job_id)

    def _watch() -> None:
        done_event.wait()
        job = context.job_store.get(job_id)
        if job is not None and job["status"] == "running":
            context.job_store.mark_completed(job_id)

    downloader.download_in_background(
        spec,
        models_dir,
        context.notifier,
        cancel_event,
        done_event,
    )
    threading.Thread(target=_watch, daemon=True, name=f"dl-watch-{model_id}").start()
    return {"job_id": job_id}


def scan_local(context: AppContext) -> dict[str, Any]:
    """本地导入扫描：重新探测 models/ 目录（手动放置的模型即刻生效）。"""
    models_dir = context.work_dir.parent.parent / "models"
    found = [
        item
        for item in registry.list_models(models_dir)
        if item["status"] == "installed"
    ]
    context.notifier.log("info", f"本地导入扫描完成：{len(found)} 个模型可用")
    return {"installed": found, "total": len(found)}


def delete(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    model_id = str(params.get("model_id", ""))
    spec = downloader.spec_by_id(model_id)
    if spec is None:
        raise RpcDomainError(_ERR_MODEL_NOT_FOUND, f"未知模型: {model_id}")
    models_dir = context.work_dir.parent.parent / "models"
    resolved = registry.find(spec, models_dir)
    if resolved is None:
        raise RpcDomainError(_ERR_MODEL_STATE, f"{spec.name} 未安装")
    # 只允许删除 models/ 目录内的内容（防误删仓库文件）
    root = models_dir.resolve()
    target = resolved.resolve()
    if root not in target.parents:
        raise RpcDomainError(_ERR_MODEL_STATE, "目标不在模型目录内，拒绝删除")
    shutil.rmtree(target, ignore_errors=True)
    return {"ok": True}
