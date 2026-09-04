"""本地套接字客户端：Windows 命名管道 / Unix domain socket，NDJSON 分帧。"""

from __future__ import annotations

import json
import socket
import sys
import threading
from collections.abc import Callable
from typing import IO, Any, cast

MAX_LINE_BYTES = 16 * 1024 * 1024
_READ_CHUNK = 65536
_PIPE_PREFIX = "\\\\.\\pipe\\"

MessageHandler = Callable[[dict[str, Any]], None]
DisconnectHandler = Callable[[], None]


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

    Windows：命名管道以文件句柄打开（byte 模式，CreateFile 客户端）；
    其他平台：AF_UNIX socket。EOF/断开 → on_disconnect → 由上层决定退出进程。
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
        self._sock: socket.socket | None = None
        if sys.platform == "win32" and address.startswith(_PIPE_PREFIX):
            handle: IO[bytes] = open(address, "r+b", buffering=0)  # noqa: SIM115 - 管道生命周期由本类管理
            self._reader: IO[bytes] = handle
            self._writer: IO[bytes] = handle
        else:
            # Windows 类型存根无 AF_UNIX；运行时此分支仅在非 Windows 走到
            unix_family = int(getattr(socket, "AF_UNIX"))  # noqa: B009 - 为 mypy 平台兼容保留 getattr
            sock = socket.socket(unix_family, socket.SOCK_STREAM)
            sock.connect(address)
            self._sock = sock
            self._reader = cast(IO[bytes], sock.makefile("rb", buffering=0))
            self._writer = cast(IO[bytes], sock.makefile("wb", buffering=0))

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
            if self._sock is not None:
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
