"""fetch 原语：Range 续传、镜像忽略 Range 时覆盖写、size/SHA256 校验与取消。"""

from __future__ import annotations

import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from dramaclip.infra.model_manager import fetch

_FILES: dict[str, bytes] = {"/model.bin": b"0123456789" * 8}
_IGNORE_RANGE = False


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server 约定
        data = _FILES.get(self.path, b"")
        if not data:
            self.send_error(404)
            return
        rng = self.headers.get("Range")
        if rng and not _IGNORE_RANGE:
            start = int(str(rng).split("=")[1].split("-")[0])
            chunk = data[start:]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
        else:
            chunk = data
            self.send_response(200)
        self.send_header("Content-Length", str(len(chunk)))
        self.end_headers()
        self.wfile.write(chunk)

    def log_message(self, *args: Any) -> None:  # 静默测试输出
        return


@pytest.fixture()
def server() -> object:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"  # type: ignore[attr-defined]
    httpd.shutdown()


def _get(tmp_path: Path, base: str) -> tuple[Path, Path]:
    dest = tmp_path / "model.bin"
    url = f"{base}/model.bin"
    return dest, url


def test_download_then_resume_from_partial(tmp_path: Path, server: str) -> None:
    dest, url = _get(tmp_path, server)
    payload = _FILES["/model.bin"]
    partial = dest.with_name(dest.name + fetch.TMP_SUFFIX)
    partial.write_bytes(payload[:16])  # 模拟上次中断
    fetch.download_file(url, dest, len(payload), cancel=threading.Event())
    assert dest.read_bytes() == payload
    assert not partial.exists()


def test_ignored_range_overwrites_instead_of_append(tmp_path: Path, server: str) -> None:
    global _IGNORE_RANGE
    _IGNORE_RANGE = True
    try:
        dest, url = _get(tmp_path, server)
        payload = _FILES["/model.bin"]
        dest.with_name(dest.name + fetch.TMP_SUFFIX).write_bytes(b"JUNK" * 16)
        fetch.download_file(url, dest, len(payload), cancel=threading.Event())
        assert dest.read_bytes() == payload
    finally:
        _IGNORE_RANGE = False


def test_size_mismatch_rejects(tmp_path: Path, server: str) -> None:
    dest, url = _get(tmp_path, server)
    with pytest.raises(IOError, match="大小校验失败"):
        fetch.download_file(url, dest, 999999, cancel=threading.Event())
    assert not dest.exists()
    assert not dest.with_name(dest.name + fetch.TMP_SUFFIX).exists()


def test_sha256_match_passes(tmp_path: Path, server: str) -> None:
    dest, url = _get(tmp_path, server)
    payload = _FILES["/model.bin"]
    fetch.download_file(
        url,
        dest,
        len(payload),
        expected_sha256=hashlib.sha256(payload).hexdigest().upper(),  # 大小写不敏感
        cancel=threading.Event(),
    )
    assert dest.read_bytes() == payload


def test_sha256_mismatch_deletes_partial(tmp_path: Path, server: str) -> None:
    """哈希不对的半成品必须删干净：留着它，下次续传会把坏内容当合法前缀接着拼。"""
    dest, url = _get(tmp_path, server)
    with pytest.raises(IOError, match="SHA256 校验失败"):
        fetch.download_file(
            url, dest, len(_FILES["/model.bin"]), expected_sha256="0" * 64,
            cancel=threading.Event(),
        )
    assert not dest.exists()
    assert not dest.with_name(dest.name + fetch.TMP_SUFFIX).exists()


def test_cancelled_before_read(tmp_path: Path, server: str) -> None:
    dest, url = _get(tmp_path, server)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(fetch.DownloadCancelled):
        fetch.download_file(url, dest, 0, cancel=cancel)


def test_sha256_and_blob_id_single_pass(tmp_path: Path) -> None:
    """一次读盘两个哈希：sha256 与单算法一致；blob_id 是 git 对象 SHA1
    （头 ``blob <字节数>\\0`` + 内容）——trees 清单的 blob_id 按本机现算，
    不用触网抄上游 oid。对照实现故意用一把梭（非流式）：抓头格式与分块错误。"""
    payload = b"hello world" * 100
    path = tmp_path / "model.bin"
    path.write_bytes(payload)
    sha256, blob_id = fetch.sha256_and_blob_id_of(path)
    assert sha256 == hashlib.sha256(payload).hexdigest()
    header = b"blob " + str(len(payload)).encode("ascii") + b"\0"
    assert blob_id == hashlib.sha1(header + payload).hexdigest()
