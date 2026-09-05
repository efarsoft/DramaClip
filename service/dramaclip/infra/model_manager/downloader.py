"""模型下载与本地导入。

下载：ModelScope 优先 → HuggingFace（hf-mirror 镜像）降级；管线在后台线程执行，
进度经 Notifier 推送。**手动导入同等为一等能力**：importer 扫描 models/ 下已放置的
模型目录并直接登记（网络不可达时的正道，用户已要求提供下载指引）。
"""

from __future__ import annotations

import threading
from pathlib import Path

from dramaclip.infra.model_manager.registry import ModelSpec, builtin_specs
from dramaclip.transport.notify import Notifier


def spec_by_id(model_id: str) -> ModelSpec | None:
    return next((spec for spec in builtin_specs() if spec.model_id == model_id), None)


def download_in_background(
    spec: ModelSpec,
    models_dir: Path,
    notifier: Notifier,
    cancel: threading.Event,
    on_done: threading.Event,
) -> threading.Thread:
    """后台线程下载。ModelScope 优先（国内直连），失败降级 hf-mirror，再失败官方 HF。"""

    def _work() -> None:
        try:
            _download_modelscope(spec, models_dir, notifier, cancel)
        except Exception as scope_error:
            if cancel.is_set():
                on_done.set()
                return
            notifier.log("warn", f"ModelScope 下载失败（{scope_error}），降级 HuggingFace 镜像")
            try:
                _download_huggingface(spec, models_dir, notifier, cancel, mirror=True)
            except Exception as mirror_error:
                if cancel.is_set():
                    on_done.set()
                    return
                notifier.log(
                    "warn",
                    "镜像亦失败。请手动下载后放入模型目录并在「模型管理」页点击扫描导入："
                    f"{_manual_guide(spec, models_dir)}",
                )
                raise mirror_error
        finally:
            on_done.set()

    thread = threading.Thread(target=_work, name=f"dl-{spec.model_id}", daemon=True)
    thread.start()
    return thread


def _manual_guide(spec: ModelSpec, models_dir: Path) -> str:
    return (
        f"仓库 {spec.repo_id} → 目标目录 {models_dir / spec.placement}"
    )


def _download_modelscope(
    spec: ModelSpec,
    models_dir: Path,
    notifier: Notifier,
    cancel: threading.Event,  # noqa: ARG001 - 下载库轮询取消标志（W10 简化版暂未接入）
) -> None:
    try:
        from modelscope import snapshot_download as ms_download  # 可选依赖
    except ImportError as exc:
        raise RuntimeError("未安装 modelscope 包") from exc
    target = models_dir / spec.placement
    notifier.log("info", f"开始从 ModelScope 下载 {spec.repo_id}")
    ms_download(spec.repo_id, local_dir=str(target))
    notifier.log("info", f"ModelScope 下载完成: {spec.name}")


def _download_huggingface(
    spec: ModelSpec,
    models_dir: Path,
    notifier: Notifier,
    cancel: threading.Event,  # noqa: ARG001 - 同上
    *,
    mirror: bool,
) -> None:
    from huggingface_hub import snapshot_download  # 可选依赖

    endpoint = "https://hf-mirror.com" if mirror else "https://huggingface.co"
    target = models_dir / spec.placement
    notifier.log("info", f"开始从 {endpoint} 下载 {spec.repo_id}")
    snapshot_download(
        spec.repo_id,
        local_dir=str(target),
        endpoint=endpoint,
        max_workers=2,
    )
    notifier.log("info", f"HuggingFace 下载完成: {spec.name}")
