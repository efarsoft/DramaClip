"""
SubprocessTTSBackend — DramaClip 版本的进程隔离 TTS 后端基类

严格参考 reference/OmniVoice-Studio/backend/services/subprocess_backend.py 的设计理念，
但针对 DramaClip 的桌面应用场景做了合理简化（Windows 优先、无完整 GPU Pool）。

核心目标：
- 把依赖冲突严重的本地 TTS 引擎（CosyVoice3、未来 IndexTTS2、FishSpeech 等）隔离在独立进程中。
- 父进程（主 DramaClip Python）通过长度前缀 JSON 协议与 sidecar 通信。
- 提供真正诚实的 is_available() 和“一键修复运行时”能力。

设计要点（来自参考项目）：
- 不使用 multiprocessing（无法使用不同 Python 解释器）。
- 使用 subprocess + 独立 venv（或至少独立进程）。
- 长度前缀 JSON 协议（4字节大端长度 + JSON）。
- 进程组隔离（Windows CREATE_NEW_PROCESS_GROUP）。
- 健壮的生命周期、超时、stderr 排水、错误处理。
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import struct
import subprocess
import sys
import threading
from abc import abstractmethod
from pathlib import Path
from typing import Optional, Dict, Any

import torch
from loguru import logger

from app.services.tts.tts_backend import TTSBackend


# ── 协议常量（与参考项目保持一致）─────────────────────────────────────────────

MAX_FRAME_BYTES = 64 * 1024 * 1024
RECV_TIMEOUT_S = 90.0          # CosyVoice 冷加载可能较慢
SPAWN_READY_TIMEOUT_S = 45.0

PARENT_INBOUND_OPS = frozenset({"ready", "pong", "audio", "progress", "error"})


class SubprocessTTSBackend(TTSBackend):
    """
    进程隔离 TTS 后端基类。

    子类只需实现两个类方法：
        @classmethod
        def venv_python(cls) -> Path: ...
        @classmethod
        def sidecar_script(cls) -> Path: ...

    其余全部由基类负责（spawn、协议、生命周期、错误处理）。
    """

    _is_subprocess_isolated: bool = True

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._stderr_thread: Optional[threading.Thread] = None
        atexit.register(self.shutdown)

    # ── 子类必须实现的契约 ────────────────────────────────────────────────────

    @classmethod
    @abstractmethod
    def venv_python(cls) -> Path:
        """
        返回运行 sidecar 的 Python 解释器路径。
        生产环境应返回该引擎专属 venv 的 python.exe。
        测试/回退可返回 sys.executable。
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def sidecar_script(cls) -> Path:
        """返回 sidecar 入口脚本路径（例如 engines/cosyvoice/main.py）。"""
        raise NotImplementedError

    # ── 生命周期管理 ──────────────────────────────────────────────────────────

    def _spawn(self) -> None:
        """启动 sidecar（如果尚未运行）。调用者必须持有 self._lock。"""
        if self._proc is not None and self._proc.poll() is None:
            return

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        kwargs: Dict[str, Any] = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "env": env,
            "bufsize": 0,
        }

        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        python_path = str(self.venv_python())
        script_path = str(self.sidecar_script())

        logger.info(f"[{self.id}] 正在启动隔离 sidecar: {python_path} {script_path}")

        try:
            self._proc = subprocess.Popen([python_path, script_path], **kwargs)
        except Exception as e:
            raise RuntimeError(f"无法启动 {self.id} sidecar: {e}") from e

        # 后台排水 stderr（避免 sidecar 阻塞）
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, daemon=True, name=f"{self.id}-stderr-drain"
        )
        self._stderr_thread.start()

        # 等待 ready 握手
        try:
            frame = self._recv_with_timeout(SPAWN_READY_TIMEOUT_S)
            if not frame or frame.get("op") != "ready":
                self._force_kill()
                raise RuntimeError(f"{self.id} sidecar 未发送 ready: {frame!r}")
            logger.info(f"[{self.id}] sidecar 已就绪")
        except Exception:
            self._force_kill()
            raise

    def shutdown(self) -> None:
        """幂等关闭 sidecar。"""
        proc = self._proc
        if proc is None:
            return
        try:
            try:
                self._send({"op": "shutdown"})
            except Exception:
                pass
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        finally:
            self._proc = None

    def unload(self) -> None:
        self.shutdown()

    def _force_kill(self) -> None:
        if self._proc:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None

    # ── 核心生成接口 ──────────────────────────────────────────────────────────

    def generate(self, text: str, **kwargs) -> torch.Tensor:
        """
        通过 sidecar 生成语音。
        返回 (1, n_samples) 的 torch.Tensor。
        """
        with self._lock:
            self._spawn()
            msg = {"op": "synthesize", "text": text}

            # 只传递 JSON 可序列化的参数
            for k, v in kwargs.items():
                if isinstance(v, (str, int, float, bool, list, dict, type(None))):
                    msg[k] = v

            self._send(msg)
            reply = self._recv_with_timeout(RECV_TIMEOUT_S)

        if not reply:
            raise RuntimeError(f"{self.id} sidecar 在生成中关闭了管道")

        if reply.get("op") == "error":
            raise RuntimeError(f"{self.id} sidecar 错误: {reply.get('message')}")

        if reply.get("op") != "audio":
            raise RuntimeError(f"{self.id} sidecar 返回了意外的 op: {reply.get('op')}")

        pcm_b64 = reply.get("audio_pcm_b64", "")
        pcm = __import__("base64").b64decode(pcm_b64)
        arr = __import__("numpy").frombuffer(pcm, dtype="int16").astype("float32") / 32768.0
        tensor = torch.from_numpy(arr.copy()).unsqueeze(0)
        return tensor

    # ── 健康检查 ──────────────────────────────────────────────────────────────

    def health_check(self) -> tuple[bool, str]:
        try:
            with self._lock:
                self._spawn()
                self._send({"op": "ping"})
                reply = self._recv_with_timeout(RECV_TIMEOUT_S)
            if reply and reply.get("op") == "pong":
                return True, "pong"
            return False, f"意外回复: {reply!r}"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    # ── 线协议实现 ────────────────────────────────────────────────────────────

    def _send(self, msg: dict) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError(f"{self.id} sidecar 未运行")
        body = json.dumps(msg, separators=(",", ":")).encode("utf-8")
        if len(body) > MAX_FRAME_BYTES:
            raise IOError(f"出站帧过大: {len(body)}")
        try:
            self._proc.stdin.write(struct.pack("!I", len(body)))
            self._proc.stdin.write(body)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise RuntimeError(f"{self.id} sidecar 管道已关闭: {exc}") from exc

    def _recv(self) -> Optional[dict]:
        if self._proc is None or self._proc.stdout is None:
            return None
        stdout = self._proc.stdout
        header = self._read_exact(stdout, 4)
        if header is None:
            return None
        (n,) = struct.unpack("!I", header)
        if n > MAX_FRAME_BYTES:
            raise IOError(f"帧过大: {n}")
        body = self._read_exact(stdout, n)
        if body is None or len(body) != n:
            raise IOError("短读")
        try:
            msg = json.loads(body.decode("utf-8"))
        except Exception as exc:
            raise IOError(f"sidecar 帧格式错误: {exc}") from exc

        op = msg.get("op") if isinstance(msg, dict) else None
        if op not in PARENT_INBOUND_OPS:
            logger.warning(f"[{self.id}] 丢弃不允许的 sidecar op: {op}")
            return self._recv()
        return msg

    def _recv_with_timeout(self, timeout_s: float) -> Optional[dict]:
        watchdog = threading.Timer(timeout_s, self._timeout_kill)
        watchdog.daemon = True
        watchdog.start()
        try:
            return self._recv()
        finally:
            watchdog.cancel()

    def _timeout_kill(self) -> None:
        if self._proc:
            logger.error(f"[{self.id}] sidecar 超过接收超时，正在杀死...")
            try:
                self._proc.kill()
            except Exception:
                pass

    def _read_exact(self, stream, n: int) -> Optional[bytes]:
        buf = bytearray()
        while len(buf) < n:
            chunk = stream.read(n - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)

    def _drain_stderr(self) -> None:
        proc = self._proc
        if not proc or not proc.stderr:
            return
        try:
            for raw in iter(proc.stderr.readline, b""):
                try:
                    line = raw.decode("utf-8", errors="replace").rstrip()
                    if line:
                        logger.debug(f"[{self.id}] {line}")
                except Exception:
                    pass
        except Exception:
            pass


def _is_jsonable(v: Any) -> bool:
    if v is None or isinstance(v, (str, int, float, bool)):
        return True
    if isinstance(v, (list, dict)):
        try:
            json.dumps(v)
            return True
        except Exception:
            return False
    return False
