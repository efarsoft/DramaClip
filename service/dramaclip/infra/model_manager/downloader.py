"""模型多源下载：ModelScope / HF 镜像 / HF 官方，所选源优先 + 国内优先降级。

逐文件管线：列文件树 → 逐个直链下载（.download 续传 + size 校验），
不依赖 huggingface_hub / modelscope 运行库。faster-whisper 落盘保持
HF 缓存布局（models--*--*/snapshots/），与手动放置的模型互相兼容。
"""

from __future__ import annotations

import re
import threading
import urllib.parse
from pathlib import Path

from dramaclip.infra.model_manager import fetch
from dramaclip.infra.model_manager.fetch import DownloadCancelled
from dramaclip.infra.model_manager.registry import ModelSpec, builtin_specs
from dramaclip.transport.notify import Notifier

Endpoints = dict[str, str]

# 国内优先的规范源序；用户所选源永远排第一
SOURCE_ORDER: tuple[str, ...] = ("modelscope", "hf_mirror", "huggingface")
_SKIP_RE = re.compile(
    r"\.(wav|mp3|flac|m4a|aac|ogg|jpg|jpeg|png|gif|webp|mp4|avi|mkv|zip|gz|xz|7z|md|pdf)$",
    re.I,
)


def spec_by_id(model_id: str) -> ModelSpec | None:
    return next((spec for spec in builtin_specs() if spec.model_id == model_id), None)


def source_chain(selected: str, spec: ModelSpec) -> list[tuple[str, str]]:
    """下载源序列：所选源排第一，其余按国内优先补齐。"""
    repos = dict(spec.sources())
    chain = [kind for kind in SOURCE_ORDER if kind in repos]
    if selected in chain:
        chain.remove(selected)
        chain.insert(0, selected)
    return [(kind, repos[kind]) for kind in chain]


def web_url(kind: str, repo: str, endpoints: Endpoints) -> str:
    """源的仓库主页（复制链接用）。"""
    if kind == "modelscope":
        return f"{endpoints['modelscope'].rstrip('/')}/models/{repo}"
    host = endpoints["hf_mirror"] if kind == "hf_mirror" else endpoints["huggingface"]
    return f"{host.rstrip('/')}/{repo}"


def download_in_background(
    spec: ModelSpec,
    models_dir: Path,
    notifier: Notifier,
    cancel: threading.Event,
    on_done: threading.Event,
    *,
    endpoints: Endpoints,
    source: str = "auto",
) -> threading.Thread:
    """后台线程逐文件下载；所选源失败自动降级其余源（国内优先）。"""

    def _work() -> None:
        try:
            _run_chain(spec, models_dir, notifier, cancel, endpoints, source)
            notifier.model_download(spec.model_id, 100.0, status="done")
        except DownloadCancelled:
            notifier.log("warn", f"{spec.name} 下载已取消")
        except Exception as exc:
            notifier.model_download(spec.model_id, 0.0, status="failed")
            notifier.log(
                "warn",
                f"{spec.name} 下载失败。可手动下载后放入 {models_dir / spec.placement} "
                f"并点击「重新检测」导入（{exc}）",
            )
        finally:
            on_done.set()

    thread = threading.Thread(target=_work, name=f"dl-{spec.model_id}", daemon=True)
    thread.start()
    return thread


def _run_chain(
    spec: ModelSpec,
    models_dir: Path,
    notifier: Notifier,
    cancel: threading.Event,
    endpoints: Endpoints,
    source: str,
) -> None:
    last_error: Exception | None = None
    for kind, repo in source_chain(source, spec):
        try:
            _download_from(kind, repo, spec, models_dir, endpoints, notifier, cancel)
            notifier.log("info", f"{spec.name} 下载完成（来源：{kind}）")
            return
        except DownloadCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - 单源失败降级下一来源
            last_error = exc
            if cancel.is_set():
                raise DownloadCancelled from exc
            notifier.log("warn", f"源 {kind} 下载失败（{exc}），尝试下一来源")
    raise RuntimeError(f"全部来源失败：{last_error}")


def _download_from(
    kind: str,
    repo: str,
    spec: ModelSpec,
    models_dir: Path,
    endpoints: Endpoints,
    notifier: Notifier,
    cancel: threading.Event,
) -> None:
    files = list_tree(kind, repo, endpoints)
    if not files:
        raise RuntimeError("仓库文件清单为空")
    notifier.log("info", f"开始从 {kind} 下载 {spec.name}（{len(files)} 个文件）")
    total = sum(size for _rel, size in files)
    state = {"done": 0, "base": 0, "percent": -1}

    def _report(position: int) -> None:
        percent = (state["base"] + position) / total * 100 if total > 0 else 0
        whole = int(percent)
        if whole != state["percent"]:
            state["percent"] = whole
            notifier.model_download(spec.model_id, min(percent, 99.0), status="downloading")

    for rel, size in files:
        dest = _dest(models_dir, spec, rel)
        if dest.is_file() and (size <= 0 or dest.stat().st_size == size):
            state["done"] += size
            continue
        url = file_url(kind, repo, rel, endpoints)
        state["base"] = state["done"]
        for attempt in (1, 2):
            try:
                fetch.download_file(url, dest, size, cancel=cancel, on_progress=_report)
                break
            except DownloadCancelled:
                raise
            except Exception:
                if attempt == 2:
                    raise
        state["done"] += size


def list_tree(kind: str, repo: str, endpoints: Endpoints) -> list[tuple[str, int]]:
    """列仓库文件清单 [(相对路径, 大小字节)]（过滤隐藏文件/文档/媒体/归档杂项）。"""

    def _wanted(rel: str) -> bool:
        hidden = rel.startswith(".") or Path(rel).name.startswith(".")
        return not hidden and not _SKIP_RE.search(rel)

    if kind == "modelscope":
        base = endpoints["modelscope"].rstrip("/")
        api = f"{base}/api/v1/models/{repo}/repo/files?Revision=master&Recursive=true"
        data = fetch.fetch_json(api)
        files = (data.get("Data") or {}).get("Files") if isinstance(data, dict) else None
        return [
            (str(item["Path"]), int(item.get("Size") or 0))
            for item in (files or [])
            if item.get("Type") == "blob" and _wanted(str(item["Path"]))
        ]
    host = endpoints["hf_mirror"] if kind == "hf_mirror" else endpoints["huggingface"]
    data = fetch.fetch_json(f"{host.rstrip('/')}/api/models/{repo}/tree/main?recursive=true")
    if not isinstance(data, list):
        return []
    out: list[tuple[str, int]] = []
    for item in data:
        if not isinstance(item, dict) or item.get("type") != "file":
            continue
        path = str(item.get("path", ""))
        if not _wanted(path):
            continue
        size = int((item.get("lfs") or {}).get("size") or item.get("size") or 0)
        out.append((path, size))
    return out


def file_url(kind: str, repo: str, rel: str, endpoints: Endpoints) -> str:
    quoted = urllib.parse.quote(rel, safe="/")
    if kind == "modelscope":
        return f"{endpoints['modelscope'].rstrip('/')}/models/{repo}/resolve/master/{quoted}"
    host = endpoints["hf_mirror"] if kind == "hf_mirror" else endpoints["huggingface"]
    return f"{host.rstrip('/')}/{repo}/resolve/main/{quoted}"


def _dest(models_dir: Path, spec: ModelSpec, rel: str) -> Path:
    """落盘路径：faster-whisper 保持 HF 缓存布局，其余平铺在 placement 下。"""
    root = models_dir / spec.placement
    if spec.engine == "faster_whisper":
        cache = f"models--{spec.repo_id.replace('/', '--')}"
        return root / cache / "snapshots" / "main" / rel
    return root / rel
