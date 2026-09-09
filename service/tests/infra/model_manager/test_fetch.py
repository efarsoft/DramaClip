"""fetch 原语：Range 续传、镜像忽略 Range 时覆盖写、size 校验与取消。"""

from __future__ import annotations

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
    partial = dest.with_name(dest.name + ".download")
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
        dest.with_name(dest.name + ".download").write_bytes(b"JUNK" * 16)
        fetch.download_file(url, dest, len(payload), cancel=threading.Event())
        assert dest.read_bytes() == payload
    finally:
        _IGNORE_RANGE = False


def test_size_mismatch_rejects(tmp_path: Path, server: str) -> None:
    dest, url = _get(tmp_path, server)
    with pytest.raises(IOError, match="大小校验失败"):
        fetch.download_file(url, dest, 999999, cancel=threading.Event())
    assert not dest.exists()
    assert not dest.with_name(dest.name + ".download").exists()


def test_cancelled_before_read(tmp_path: Path, server: str) -> None:
    dest, url = _get(tmp_path, server)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(fetch.DownloadCancelled):
        fetch.download_file(url, dest, 0, cancel=cancel)
