"""本地 TTS worker 进程桥单源：常驻 worker + 行 JSON 协议的一生（cosyvoice/indextts2）。

为什么收这里：两引擎各自维护一份逐行同形的一生（spawn/就绪握手/一问一答/退出收尸/
分块拼接）。看门狗修复（worker 卡死 → IO 锁永久排队，服务 ping 正常但合成全链锁死）
当年只落了 indextts2——cosyvoice 定义了超时常量却仍用裸 readline，同款暴露面一直
开着。收单源后看门狗/握手记账/收尸两引擎同时拥有。

状态语义：每个引擎模块持有一个 WorkerBridge 实例，进程与就绪行记账全是实例态——
factory 每次 new 引擎实例、worker 按引擎共享，与原模块级全局完全同构。

协议（两 worker 逐字同形）：就绪行 ``{"ready": true, ...}`` 只发一次，按进程对象身份
记账（respawn 出新对象天然重置）；请求 ``{"id","text","voice","out"}``；应答
``{"id","ok": true|false,"error"?}``。
"""

from __future__ import annotations

import json
import os
import subprocess  # noqa: S404 - 固定解释器固定参数
import threading
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dramaclip.infra.model_manager import worker_bridge


def readline_with_watchdog(
    proc: subprocess.Popen[str], timeout_s: float, what: str, label: str
) -> str:
    """带看门狗的应答读取：worker 卡死（GPU stall / OOM 挂起不退出）时，超时杀
    进程让阻塞中的 readline 以 EOF 返回——IO 锁得以释放、下一位调用者经 ensure()
    自动重建。此前两处 readline 均无超时的教训：一次挂死 = 合成/试听全链在锁上
    永久排队，服务 ping 正常却不可用，只能重启进程。"""
    timed_out = threading.Event()

    def _kill() -> None:
        timed_out.set()
        proc.kill()

    timer = threading.Timer(timeout_s, _kill)
    timer.daemon = True
    timer.start()
    try:
        stdout = proc.stdout
        assert stdout is not None
        line = stdout.readline()
    finally:
        timer.cancel()
    if timed_out.is_set() or not line:
        raise RuntimeError(
            f"{label} worker {what}超时/无应答"
            f"（{timeout_s:.0f}s 看门狗已杀进程，下次合成自动重建）"
        )
    return line


def concat_wav(parts: list[Path], out_path: Path) -> None:
    """同参 wav 按帧拼接（两 worker 都恒定单声道 16bit；采样率由引擎各自注释）。

    直接拼 PCM 帧不做 crossfade：块间 worker 自己落静音间隔（infer 默认参数），
    再叠 crossfade 反而削掉句间停顿。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as out_wav:
        params_set = False
        for part in parts:
            with wave.open(str(part), "rb") as in_wav:
                if not params_set:
                    out_wav.setnchannels(in_wav.getnchannels())
                    out_wav.setsampwidth(in_wav.getsampwidth())
                    out_wav.setframerate(in_wav.getframerate())
                    params_set = True
                out_wav.writeframes(in_wav.readframes(in_wav.getnframes()))


class WorkerBridge:
    """一个引擎的常驻 worker 会话：spawn/握手/一问一答/收尸，实例态即引擎态。"""

    def __init__(
        self,
        *,
        label: str,
        worker_src: Path,
        venv_python: Callable[[], Path],
        env: Callable[[], dict[str, str]],
        launch_timeout_s: float,
        synth_timeout_s: float,
        pre_spawn: Callable[[Path | None], None] | None = None,
    ) -> None:
        self._label = label
        self._worker_src = worker_src
        self._venv_python = venv_python
        self._env = env
        self._launch_timeout_s = launch_timeout_s
        self._synth_timeout_s = synth_timeout_s
        self._pre_spawn = pre_spawn
        self._lock = threading.Lock()
        # 共享 worker 的 stdin/stdout 一问一答整段持锁：试听（RPC 执行池）与出片
        # 任务的合成并发打同一进程时，无锁的 write/readline 会应答错配拿到别人的音频。
        self._io_lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._proc_device: str | None = None
        # 就绪行整个 worker 生命周期只发一次，按进程对象身份记账（respawn 天然重置；
        # 记在引擎实例上会让第二个实例永远挂在 readline——indextts2 踩过的坑）。
        self._hello: dict[subprocess.Popen[str], dict[str, Any]] = {}

    def ensure(
        self, models_dir: Path | None, device: str = "auto"
    ) -> subprocess.Popen[str]:
        with self._lock:
            if self._proc is not None:
                alive = self._proc.poll() is None
                if alive and device == self._proc_device:
                    return self._proc
                # 死进程/设备承诺变了：旧进程的就绪行随进程一起作废
                self._hello.pop(self._proc, None)
                if alive:
                    self._proc.terminate()
                self._proc = None
            if self._pre_spawn is not None:
                self._pre_spawn(models_dir)
            # device 交给 worker 内 torch 自检（老卡新栈无内核，载入才崩——最小
            # 运算探针失败即回 CPU）。stderr 走继承：加载诊断落进服务日志，不盲飞。
            self._proc = subprocess.Popen(  # noqa: S603 - 固定脚本固定参数
                [str(self._venv_python()), str(self._worker_src), str(models_dir), device],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                env={**os.environ, **self._env()},
            )
            self._proc_device = device
            # 优雅退出路径（service_app 的 worker_bridge.shutdown_venv_workers）
            # 一并收走本桥——此前 cosyvoice 的收尸函数全仓无人调用，Windows 上
            # 留孤儿进程占着模型内存。登记一次即可，shutdown 幂等随便重入。
            worker_bridge.register_process_reaper(self.shutdown)
            return self._proc

    def shutdown(self) -> None:
        with self._io_lock:
            proc = self._proc
            self._proc = None
            self._proc_device = None
            if proc is not None:
                self._hello.pop(proc, None)
        if proc is not None and proc.poll() is None:
            proc.terminate()

    def current_proc(self) -> subprocess.Popen[str] | None:
        return self._proc

    def hello_of(self, proc: subprocess.Popen[str]) -> dict[str, Any] | None:
        return self._hello.get(proc)

    def synth_one(
        self, proc: subprocess.Popen[str], text: str, ref: str, out_path: Path
    ) -> None:
        """送一个 job 给 worker 并等应答。整段持 IO 锁：一问一答中间不许插队。"""
        with self._io_lock:
            if proc.stdin is None or proc.stdout is None:
                raise RuntimeError("worker 进程管道不可用")
            hello = self._hello.get(proc)
            if hello is None:
                line = readline_with_watchdog(
                    proc, self._launch_timeout_s, "就绪握手", self._label
                )
                try:
                    hello = json.loads(line)
                except ValueError as exc:
                    raise RuntimeError("worker 未返回可解析的就绪行") from exc
                if not hello.get("ready"):
                    raise RuntimeError(f"worker 启动失败：{hello.get('error', '未知原因')}")
                self._hello[proc] = hello
            job = {"id": "0", "text": text, "voice": ref, "out": str(out_path)}
            proc.stdin.write(json.dumps(job, ensure_ascii=False) + "\n")
            proc.stdin.flush()
            reply = json.loads(
                readline_with_watchdog(proc, self._synth_timeout_s, "合成应答", self._label)
            )
            if not reply.get("ok"):
                raise RuntimeError(f"{self._label} 合成失败：{reply.get('error', '未知错误')}")
