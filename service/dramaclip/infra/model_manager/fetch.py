"""下载原语：JSON API 拉取 + 单文件 Range 续传下载（stdlib，零第三方依赖）。
"""

from __future__ import annotations

import hashlib
import json
import threading
import urllib.request
from collections.abc import Callable
from pathlib import Path

_CHUNK = 1 << 20  # 1 MiB
_UA = "DramaClip/2.0"

#: 半成品统一后缀：资产体检的残留判据（registry._verify_residue）扫的就是 ``*.incomplete``。
#: 自家下载器的半成品必须能被体检看见并可被「清理残留」收走——曾经用 ``.download``，
#: 结果是自己的断点文件对体检永久隐身，只有别的工具（hf hub）的残留看得见。
TMP_SUFFIX = ".incomplete"


class DownloadCancelled(Exception):
    """用户取消下载（经 cancel Event 触发）。"""


def fetch_json(url: str, *, timeout: float = 30.0) -> object:
    """GET 并解析 JSON（带 UA；HTTP 错误抛 URLError/HTTPError）。"""
    request = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def sha256_of(path: Path) -> str:
    """整文件 SHA256（十六进制小写）。落盘后校验与迁移补清单共用这一处实现。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_and_blob_id_of(path: Path) -> tuple[str, str]:
    """一次读盘同时算两个哈希：内容 SHA256 + git blob SHA1（HF trees 清单的 blob_id）。

    git blob 头就是 ``blob <字节数>\\0``：本机可算、不依赖网络，算出来的是
    「这份盘上字节的 git 身份」——relayout 补清单时比抄上游 API 的 oid 更诚实
    （对账对的就是本机这份）。1.5GB 的权重也只读一遍。
    """
    sha256 = hashlib.sha256()
    sha1 = hashlib.sha1()
    size = path.stat().st_size
    sha1.update(b"blob " + str(size).encode("ascii") + b"\0")
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            sha256.update(chunk)
            sha1.update(chunk)
    return sha256.hexdigest(), sha1.hexdigest()


def download_file(
    url: str,
    dest: Path,
    expected_size: int,
    *,
    expected_sha256: str | None = None,
    cancel: threading.Event,
    on_progress: Callable[[int], None] | None = None,
) -> None:
    """下载单文件到 dest（.incomplete 续传 + 大小/SHA256 校验 + 原子改名落位）。

    ``expected_sha256`` 给得上就逐字节对账（HF 的 lfs.oid / ModelScope 的 Sha256 都是
    文件内容的 SHA256）：只比字节数的校验放得过「长度碰巧对、内容断了半截」的文件。
    校验失败的半成品直接删——留着它，下次续传会把坏内容当合法前缀接着拼。
    """
    tmp = dest.with_name(dest.name + TMP_SUFFIX)
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
    if expected_sha256:
        digest = sha256_of(tmp)
        if digest != expected_sha256.strip().lower():
            tmp.unlink(missing_ok=True)
            raise OSError(
                f"SHA256 校验失败：期望 {expected_sha256[:12]}…，实际 {digest[:12]}…"
                "（半成品已删，重试将整文件重下）"
            )
    if dest.exists():
        dest.unlink()
    tmp.replace(dest)
