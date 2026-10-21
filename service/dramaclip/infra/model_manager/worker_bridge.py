"""venv worker 进程桥：本地智能运行环境解释器 + 逐行 JSON 协议的通用会话。

消费者（funasr ASR / kokoro TTS / 后续 torch 系）各自提供自包含 worker 脚本
（venv 进程不能 import dramaclip），本桥只管：spawn、就绪握手、按 id 配对的
请求应答、进程回收。协议约定见各 worker 文件头（与 indextts_worker 同构：
fd 1 换 stderr 保 JSON 通道、ready 行、{"id","ok",...} 应答）。
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_ACTIVE_WORKERS: list[VenvWorker] = []
_ACTIVE_LOCK = threading.Lock()


class VenvWorker:
    """一行请求一行应答的 venv worker 会话；单 worker 串行（模型推理本就不可并发）。"""

    def __init__(self, worker_src: Path, config: dict[str, Any]) -> None:
        self._worker_src = worker_src
        self._config = config
        self._proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self.ready: dict[str, Any] | None = None

    @property
    def proc(self) -> subprocess.Popen[str] | None:
        return self._proc

    def start(self) -> dict[str, Any]:
        from dramaclip.infra.model_manager import tts_runtime
        from dramaclip.infra.paths import resolve_data_dir

        py = tts_runtime.venv_python(resolve_data_dir())
        if not py.is_file():
            raise RuntimeError(
                "未装运行环境：需要本地智能运行环境（引擎页「安装运行环境」）"
            )
        try:
            self._proc = subprocess.Popen(  # noqa: S603 - 固定解释器固定脚本
                [str(py), str(self._worker_src), json.dumps(self._config, ensure_ascii=False)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                text=True, encoding="utf-8",
                # 协议是 UTF-8，父进程写 UTF-8；子进程 stdin/stdout 默认走
                # 系统 ANSI 代码页（中文 Windows 是 GBK），中文会被解成鬼字。
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                creationflags=_NO_WINDOW,
            )
        except OSError as exc:
            raise RuntimeError(f"运行环境 worker 启动失败（可重装修复）: {exc}") from exc
        ready = self._readline()
        if ready is None or not ready.get("ready"):
            self.close()
            detail = str((ready or {}).get("error") or "").strip()
            raise RuntimeError(
                f"worker 启动失败：{detail}" if detail
                else "worker 启动失败（venv 依赖不完整可重装修复）"
            )
        self.ready = ready
        return ready

    def _readline(self) -> dict[str, Any] | None:
        assert self._proc is not None and self._proc.stdout is not None
        line = self._proc.stdout.readline()
        if not line:
            return None
        try:
            value = json.loads(line)
        except ValueError:
            return None
        return dict(value) if isinstance(value, dict) else None

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        assert self._proc is not None and self._proc.stdin is not None
        with self._lock:
            req_id = uuid.uuid4().hex
            self._proc.stdin.write(
                json.dumps({"id": req_id, **payload}, ensure_ascii=False) + "\n"
            )
            self._proc.stdin.flush()
            while True:
                msg = self._readline()
                if msg is None:
                    raise RuntimeError("worker 意外退出（可重装修复运行环境）")
                if msg.get("id") != req_id:
                    continue  # 应答严格按 id 配对；异 id 只可能是残留，跳过
                return msg

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.close()
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001 - 收尾尽力而为，等不到就强杀
            proc.kill()


def register_venv_worker(worker: VenvWorker) -> None:
    """把调用方自管的 VenvWorker 入退出回收注册表（自管 start 时序的消费者用）。"""
    with _ACTIVE_LOCK:
        _ACTIVE_WORKERS.append(worker)


def spawn_venv_worker(worker_src: Path, config: dict[str, Any]) -> VenvWorker:
    """一步到位：构造 + 入册 + start（就绪握手）+ 返回。"""
    worker = VenvWorker(worker_src, config)
    register_venv_worker(worker)
    worker.start()
    return worker


def shutdown_venv_workers() -> None:
    """service_app 退出钩子：回收全部 venv worker（防孤儿占模型内存）。"""
    with _ACTIVE_LOCK:
        workers = _ACTIVE_WORKERS[:]
        _ACTIVE_WORKERS.clear()
    for worker in workers:
        worker.close()
