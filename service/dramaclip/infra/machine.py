"""本机内存/磁盘探测（零依赖，std only）——GPU 探测在 gpu.py。

磁盘取数据目录所在盘的可用空间：模型与产物都落 data/，
数据盘满才是真实约束，系统盘满不影响。
"""

from __future__ import annotations

import ctypes
import shutil
import threading
from pathlib import Path

_LOCK = threading.Lock()
_CACHE: dict[str, float] | None = None


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _query_once() -> dict[str, float]:
    stat = _MemoryStatusEx()
    stat.dwLength = ctypes.sizeof(_MemoryStatusEx)
    ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    if not ok:
        return {}
    data_dir = Path(__file__).resolve().parents[3] / "data"
    try:
        disk_free = shutil.disk_usage(data_dir).free
    except OSError:
        disk_free = shutil.disk_usage(Path.home()).free
    return {
        "ram_total_gb": round(stat.ullTotalPhys / 1024**3, 1),
        "ram_free_gb": round(stat.ullAvailPhys / 1024**3, 1),
        "disk_free_gb": round(disk_free / 1024**3, 1),
    }


def specs(force: bool = False) -> dict[str, float]:
    """内存总量/可用 + 数据盘可用（GB，一位小数）。进程内缓存，force 重测。"""
    global _CACHE
    with _LOCK:
        if _CACHE is None or force:
            try:
                _CACHE = _query_once()
            except Exception:  # noqa: BLE001 - 探测失败不阻塞 health，返回空由前端显示未知
                _CACHE = {}
        return dict(_CACHE)
