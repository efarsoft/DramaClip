"""下载原语：JSON API 拉取 + 单文件 Range 续传下载（stdlib，零第三方依赖）。

续传规则：<dest>.download 临时文件 + Range 请求；响应非 206 视为服务端忽略
Range（镜像常见行为），覆盖写重下而非追加。完成后按期望大小校验。
"""

from __future__ import annotations

import json
import threading
import urllib.request
from collections.abc import Callable
from pathlib import Path

_CHUNK = 1 << 20  # 1 MiB
_UA = "DramaClip/2.0"


class DownloadCancelled(Exception):
    """用户取消下载（经 cancel Event 触发）。"""


def fetch_json(url: str, *, timeout: float = 30.0) -> object:
    """GET 并解析 JSON（带 UA；HTTP 错误抛 URLError/HTTPError）。"""
    request = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download_file(
    url: str,
    dest: Path,
    expected_size: int,
    *,
    cancel: threading.Event,
    on_progress: Callable[[int], None] | None = None,
) -> None:
    """下载单文件到 dest（.download 续传 + 大小校验 + 原子改名落位）。

    expected_size <= 0 表示未知大小（跳过校验）；on_progress 收到已写字节数。
    """
    tmp = dest.with_name(dest.name + ".download")
    dest.parent.mkdir(parents=True, exist_ok=True)
    start = tmp.stat().st_size if tmp.is_file() else 0
    if expected_size > 0 and start > expected_size:
        tmp.unlink()
        start = 0
    headers = {"User-Agent": _UA}
    if start > 0:
        headers["Range"] = f"bytes={start}-"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as resp:
        append = start > 0 and resp.status == 206
        position = start if append else 0
        with tmp.open("ab" if append else "wb") as sink:
            while True:
                if cancel.is_set():
                    raise DownloadCancelled(url)
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                sink.write(chunk)
                position += len(chunk)
                if on_progress is not None:
                    on_progress(position)
    actual = tmp.stat().st_size
    if expected_size > 0 and actual != expected_size:
        tmp.unlink(missing_ok=True)
        raise OSError(f"大小校验失败：期望 {expected_size} 字节，实际 {actual} 字节")
    if dest.exists():
        dest.unlink()
    tmp.replace(dest)
