"""models 命名空间：list / download / scan（本地导入）/ delete。"""

from __future__ import annotations

import shutil
import threading
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.infra.jobs import STATUS_RUNNING
from dramaclip.infra.model_manager import downloader, registry
from dramaclip.transport.rpc import Router, RpcDomainError

_ERR_MODEL_NOT_FOUND = -32010
_ERR_MODEL_STATE = -32011

_ENDPOINT_DEFAULTS: dict[str, str] = {
    "hf_mirror": "https://hf-mirror.com",
    "modelscope": "https://modelscope.cn",
    "huggingface": "https://huggingface.co",
}


def endpoints(context: AppContext) -> dict[str, str]:
    """下载端点：settings 可覆盖镜像站（键 download.hf_mirror / download.ms_base）。"""
    out = dict(_ENDPOINT_DEFAULTS)
    for key, setting in (("hf_mirror", "download.hf_mirror"), ("modelscope", "download.ms_base")):
        value = (context.settings.get(setting) or "").strip()
        if value:
            out[key] = value
    return out


def register(router: Router, context: AppContext) -> None:
    router.register("models.list", lambda _params: list_models(context))
    router.register("models.download", lambda params: download(context, params))
    router.register("models.scan_local", lambda params: scan_local(context))
    router.register("models.runtime_status", lambda params: runtime_status(context, params))
    router.register("models.install_runtime", lambda params: install_runtime(context, params))
    router.register("models.delete", lambda params: delete(context, params))


def list_models(context: AppContext) -> list[dict[str, Any]]:
    """清单 + 状态（内置清单 ∪ models/ 目录手动放置的发现项），附各源仓库主页。"""
    models_dir = context.data_dir / "models"
    eps = endpoints(context)
    items = registry.list_models(models_dir)
    for item in items:
        item["sources"] = [
            {**source, "web_url": downloader.web_url(str(source["kind"]), str(source["repo"]), eps)}
            for source in item["sources"]
        ]
    return items


def download(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    model_id = str(params.get("model_id", ""))
    source = str(params.get("source") or "auto")
    spec = downloader.spec_by_id(model_id)
    if spec is None:
        raise RpcDomainError(_ERR_MODEL_NOT_FOUND, f"未知模型: {model_id}")
    if source != "auto" and source not in dict(spec.sources()):
        raise RpcDomainError(_ERR_MODEL_STATE, f"{spec.name} 不支持来源 {source}")
    models_dir = context.data_dir / "models"
    if registry.find(spec, models_dir) is not None:
        raise RpcDomainError(_ERR_MODEL_STATE, f"{spec.name} 已安装")
    job_id = context.job_store.create("model_download", ref_id=model_id)
    # 必须置 running：看门狗的回写条件是 status=="running"，而启动清扫只扫 running——
    # 不置位则下载成功后记录永远停在 pending，且重启也清不掉（队列页永久假"下载中"）。
    context.job_store.mark_running(job_id)
    cancel_event = threading.Event()
    context.cancel_events[job_id] = cancel_event
    done_event = threading.Event()

    def _watch() -> None:
        done_event.wait()
        job = context.job_store.get(job_id)
        if job is not None and job["status"] == STATUS_RUNNING:
            context.job_store.mark_completed(job_id)
        context.cancel_events.pop(job_id, None)

    downloader.download_in_background(
        spec,
        models_dir,
        context.notifier,
        cancel_event,
        done_event,
        endpoints=endpoints(context),
        source=source,
    )
    threading.Thread(target=_watch, daemon=True, name=f"dl-watch-{model_id}").start()
    return {"job_id": job_id}


def runtime_status(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """CUDA 运行库安装态（GpuCard 状态机第四档的判据）。"""
    from dramaclip.infra.model_manager import cuda_runtime

    return cuda_runtime.status(context.data_dir)


def install_runtime(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """下载并启用 CUDA 运行库（作业模式：进度走 set_progress，可取消）。"""
    from dramaclip.infra.model_manager import cuda_runtime

    if cuda_runtime.status(context.data_dir)["installed"]:
        raise RpcDomainError(_ERR_MODEL_STATE, "CUDA 运行库已安装")
    _active = [
        j for j in context.job_store.list_recent(limit=50, active_only=True)
        if j["type"] == "cuda_runtime"
    ]
    if _active:
        raise RpcDomainError(_ERR_MODEL_STATE, "已有安装任务进行中，请等待完成或取消")
    job_id = context.job_store.create("cuda_runtime", ref_id="cuda-runtime")
    context.job_store.mark_running(job_id)
    cancel_event = threading.Event()
    context.cancel_events[job_id] = cancel_event
    done_event = threading.Event()

    def _run() -> None:
        try:
            cuda_runtime.install(
                context.data_dir,
                cancel=cancel_event,
                on_progress=lambda percent: context.job_store.set_progress(
                    job_id, float(percent), "下载 CUDA 运行库"
                ),
            )
            context.notifier.log("info", "CUDA 运行库安装完成，重启服务后对已运行进程生效")
        except Exception as exc:  # noqa: BLE001 - 作业失败原样落 error
            context.job_store.mark_failed(job_id, str(exc))
        finally:
            done_event.set()

    def _watch() -> None:
        done_event.wait()
        job = context.job_store.get(job_id)
        if job is not None and job["status"] == "running":
            context.job_store.mark_completed(job_id)
        context.cancel_events.pop(job_id, None)

    threading.Thread(target=_run, daemon=True, name="cuda-runtime-install").start()
    threading.Thread(target=_watch, daemon=True, name="cuda-runtime-watch").start()
    return {"job_id": job_id}



def scan_local(context: AppContext) -> dict[str, Any]:
    """本地导入扫描：重新探测 models/ 目录（手动放置的模型即刻生效）。"""
    models_dir = context.data_dir / "models"
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
    models_dir = context.data_dir / "models"
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
