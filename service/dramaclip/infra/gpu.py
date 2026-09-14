"""GPU 探测：nvidia-smi 异步探测 + 宽容判定 + 会话缓存 + 启动预热。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import threading

_CUDA_RE = re.compile(r"CUDA(?:\s+UMD)?\s+Version\s*:\s*(\d+(?:\.\d+)?)", re.I)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_LOCK = threading.Lock()
_CACHE: dict[str, object] | None = None
_PENDING = False


def _smi_paths() -> list[str]:
    candidates = [
        shutil.which("nvidia-smi") or "",
        r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
    ]
    return [c for c in candidates if c]


def _run(path: str, args: list[str], timeout: float) -> str:
    result = subprocess.run(  # noqa: S603 - 固定路径固定参数
        [path, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=_NO_WINDOW,
    )
    return result.stdout


def parse_query_output(output: str) -> tuple[str, str]:
    """解析 --query-gpu=name,driver_version 输出首行 → (显卡名, 驱动版本)。"""
    lines = [line for line in output.strip().splitlines() if line.strip()]
    if not lines:
        return "", ""
    parts = [part.strip() for part in lines[0].split(",")]
    return (parts[0] if len(parts) > 0 else "", parts[1] if len(parts) > 1 else "")


def parse_max_cuda(output: str) -> str:
    """从 nvidia-smi 裸输出解析驱动支持的最高 CUDA 版本（兼容 UMD 改名）。"""
    match = _CUDA_RE.search(output)
    return match.group(1) if match else ""


def detect() -> dict[str, object]:
    """同步探测（阻塞，最长 ~20s）：仅由 prefetch 后台线程调用。"""
    name = driver = max_cuda = ""
    for smi in _smi_paths():
        try:
            query = ["--query-gpu=name,driver_version", "--format=csv,noheader,nounits"]
            name, driver = parse_query_output(_run(smi, query, 10.0))
            max_cuda = parse_max_cuda(_run(smi, [], 10.0))
            break
        except (OSError, subprocess.SubprocessError):
            continue
    has_nvidia = bool(name or driver or max_cuda)
    return {
        "ready": True,
        "vendor": "nvidia" if has_nvidia else "none",
        "name": name,
        "driver_version": driver,
        "max_cuda_version": max_cuda,
    }


def snapshot(force: bool = False) -> dict[str, object]:
    """非阻塞取缓存；force=True 丢弃缓存重新探测。未就绪则后台补测并返回待定态。"""
    global _CACHE
    with _LOCK:
        if force:
            _CACHE = None
        if _CACHE is not None:
            return dict(_CACHE)
    prefetch()
    return {
        "ready": False,
        "vendor": "unknown",
        "name": "",
        "driver_version": "",
        "max_cuda_version": "",
    }


def prefetch() -> None:
    """后台预热/刷新探测缓存（幂等，进行中不重复开线程）。"""
    global _PENDING

    def _work() -> None:
        global _CACHE, _PENDING
        try:
            result = detect()
        except Exception:  # noqa: BLE001 - 探测失败保持未就绪，下次再测
            return
        finally:
            with _LOCK:
                _PENDING = False
        with _LOCK:
            _CACHE = result

    with _LOCK:
        if _PENDING:
            return
        _PENDING = True
    threading.Thread(target=_work, name="gpu-detect", daemon=True).start()
