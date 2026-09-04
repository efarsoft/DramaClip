"""本地套接字客户端：127.0.0.1 环回 TCP + NDJSON 分帧（ADR-002 修订版）。

为何放弃命名管道：Python CRT 文件句柄在 Windows 管道上并发「阻塞读 + 跨线程写」
会死锁写方（实测 20 条 0 投递）。环回 TCP 两端实现均成熟、跨平台同码，
安全由 hello 阶段的 token 认证保证（不经外网栈、环回绑定无防火墙弹窗）。
"""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Callable
from typing import Any

MAX_LINE_BYTES = 16 * 1024 * 1024
_READ_CHUNK = 65536
_CONNECT_TIMEOUT_S = 10.0

MessageHandler = Callable[[dict[str, Any]], None]
DisconnectHandler = Callable[[], None]


def parse_address(address: str) -> tuple[str, int]:
    """'127.0.0.1:51800' → ('127.0.0.1', 51800)。"""
    host, _, port_text = address.rpartition(":")
    if not host or not port_text.isdigit():
        raise ValueError(f"非法服务地址: {address}")
    return host, int(port_text)


class LineAssembler:
    """字节流 → 完整行（跨块缓冲，跳过空行）。纯逻辑，单测覆盖。"""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> list[str]:
        self._buffer.extend(chunk)
        lines: list[str] = []
        while True:
            newline = self._buffer.find(b"\n")
            if newline < 0:
                break
            line = self._buffer[:newline].decode("utf-8")
            del self._buffer[: newline + 1]
            if line:
                lines.append(line)
        return lines


class ServiceConnection:
    """连接 Electron 主进程（服务端），后台线程读取入站消息。

    读/写使用 socket 的两个独立 makefile 对象，天然支持跨线程并发。
    EOF/断开 → on_disconnect → 由上层决定退出进程。
    """

    def __init__(
        self,
        address: str,
        on_message: MessageHandler,
        on_disconnect: DisconnectHandler,
    ) -> None:
        self._address = address
        self._on_message = on_message
        self._on_disconnect = on_disconnect
        self._write_lock = threading.Lock()
        self._closed = False
        self._sock = socket.create_connection(parse_address(address), timeout=_CONNECT_TIMEOUT_S)
        self._sock.settimeout(None)
        self._reader = self._sock.makefile("rb", buffering=0)
        self._writer = self._sock.makefile("wb", buffering=0)

    @property
    def address(self) -> str:
        return self._address

    def start_reader(self) -> None:
        threading.Thread(target=self._read_loop, name="ipc-reader", daemon=True).start()

    def send(self, payload: dict[str, Any]) -> None:
        """发送一行 JSON。写锁保证行原子性；超限消息直接抛错。"""
        line = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        if len(line) > MAX_LINE_BYTES:
            raise ValueError(f"出站消息超过 {MAX_LINE_BYTES} 字节上限")
        with self._write_lock:
            view = memoryview(line)
            while view:
                written = self._writer.write(view)
                if written is None or written <= 0:
                    raise OSError("套接字写入失败")
                view = view[written:]

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._reader.close()
            self._writer.close()
        finally:
            self._sock.close()

    def _read_loop(self) -> None:
        assembler = LineAssembler()
        try:
            while True:
                chunk = self._reader.read(_READ_CHUNK)
                if not chunk:
                    break
                for line in assembler.feed(chunk):
                    self._dispatch_line(line)
        except OSError:
            pass
        finally:
            self._on_disconnect()

    def _dispatch_line(self, line: str) -> None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return  # 对端为受信主进程；坏行跳过，靠心跳兜底判定连接健康
        self._on_message(payload)
