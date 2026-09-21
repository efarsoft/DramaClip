"""IndexTTS-2.5 引擎：子进程桥到隔离 venv worker（主 venv Python 3.13 与上游
`<3.12` 约束、transformers 4.52 vendored 内部 API 均不兼容，物理隔离是唯一干净解）。

worker 进程常驻（一次加载模型），按行 JSON 协议逐段合成；voice=参考音频绝对路径
（零样本克隆：任意 3~10 秒人声 wav）。首次合成前若隔离 venv 不存在，引导脚本可
重建（见 ensure_runtime）。
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

from dramaclip.infra.paths import resolve_data_dir

_WORKER_SRC = Path(__file__).parents[1] / "workers" / "indextts_worker.py"
_LAUNCH_TIMEOUT_S = 600.0  # 首次加载全模型：CPU 实测 ~25s，留足余量
_SYNTH_TIMEOUT_S = 900.0  # CPU 档单段可达 2~3 分钟（RTF≈14.5）

_LOCK = threading.Lock()
_PROC: subprocess.Popen[str] | None = None


def _venv_python() -> Path:
    return resolve_data_dir() / "runtimes" / "indextts-venv" / "Scripts" / "python.exe"


def runtime_ready() -> bool:
    """隔离 venv 可用（存在且能 import indextts）。"""
    py = _venv_python()
    if not py.is_file():
        return False
    try:
        probe = subprocess.run( # noqa: S603 - 固定路径受控参数
            [str(py), "-c", "import indextts, torch"],
            capture_output=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return probe.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _ensure_worker(models_dir: Path | None) -> subprocess.Popen[str]:
    global _PROC
    with _LOCK:
        if _PROC is not None and _PROC.poll() is None:
            return _PROC
        # device 交给 worker 内 torch 自检：探测层不区分 CUDA 代际（M4000 cc5.2 这类
        # 「有 N 卡但新栈不支持」的机器，init 失败进程即退，错误经 stdout 空行带回）。
        _PROC = subprocess.Popen( # noqa: S603 - 固定脚本固定参数
            [str(_venv_python()), str(_WORKER_SRC), str(models_dir), "auto"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return _PROC


class IndexTts2Engine:
    def __init__(self, model_dir: Path | None = None) -> None:
        self._model_dir = model_dir
        self._device = ""

    @property
    def name(self) -> str:
        return "indextts2"

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        if not runtime_ready():
            raise RuntimeError(
                "IndexTTS 运行环境未就绪：需要隔离 Python 3.11 venv"
                "（引擎页「安装运行环境」）"
            )
        if voice == "" or not Path(voice).is_file():
            raise ValueError(
                "IndexTTS 需要参考音频作为音色（任意 3~10 秒人声 wav），当前 voice 为空"
            )
        proc = _ensure_worker(self._model_dir)
        if proc.stdin is None or proc.stdout is None:
            raise RuntimeError("worker 进程管道不可用")
        if self._device == "":
            ready = json.loads(proc.stdout.readline())
            self._device = str(ready.get("device", "?"))
        job = {"id": "0", "text": text, "voice": str(Path(voice).resolve()), "out": str(out_path)}
        proc.stdin.write(json.dumps(job, ensure_ascii=False) + "\n")
        proc.stdin.flush()
        reply = json.loads(proc.stdout.readline())
        if not reply.get("ok"):
            raise RuntimeError(f"IndexTTS 合成失败：{reply.get('error', '未知错误')}")
        return out_path
