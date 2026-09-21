"""IndexTTS 运行时引导：uv 拉起独立 venv（Python 3.11 + torch + indextts 源码）。

主服务（Python 3.13）与上游 ``<3.12`` 约束不可调和——运行时是数据目录下的
独立 venv，由 uv 引导创建（uv 自动下载独立 CPython，用户机器零 Python 依赖）。
产物即 ``engines/tts/engines/indextts2.py`` 探测的同一路径（runtimes/indextts-venv）。

流程（阶段→进度）：uv.exe 下载(0-5) → venv 创建含独立 Python(5-15) →
torch(15-55, GPU 探测定 cu128/CPU 变体) → 依赖(55-85) → 源码 zip(85-97) →
import 自检(97-100)。全程多镜像容错，可取消，可重入（已存在阶段跳过）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import zipfile
from pathlib import Path
from typing import Any

from dramaclip.infra.model_manager.fetch import download_file

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_UV_VERSION = "0.8.4"
_UV_SOURCES = [
    f"https://gh-proxy.com/https://github.com/astral-sh/uv/releases/download/{_UV_VERSION}/uv-x86_64-pc-windows-msvc.zip",
    f"https://github.com/astral-sh/uv/releases/download/{_UV_VERSION}/uv-x86_64-pc-windows-msvc.zip",
]
# 独立 CPython 与 PyPI 走国内镜像（uv 官方源国内不稳）
_UV_ENV = {
    "UV_PYTHON_INSTALL_MIRROR": "https://gh-proxy.com/https://github.com/astral-sh/python-build-standalone/releases/download",
    "UV_HTTP_TIMEOUT": "120",
}
_PYPI_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
_TORCH_INDEX = "https://download.pytorch.org/whl/cu128"
_TORCH_CPU = ["torch==2.8.0", "torchaudio==2.8.0"]
_DEPS = [
    "transformers==4.52.1", "omegaconf", "accelerate", "munch", "einops",
    "descript-audiotools", "json5", "wetext", "cn2an", "jieba", "numba",
    "openai-whisper", "sentencepiece", "fugashi", "unidic-lite", "g2p-en",
    "modelscope==1.27.0",
]
_SRC_TAG = "main"
_SRC_SOURCES = [
    f"https://gh-proxy.com/https://github.com/index-tts/index-tts/archive/refs/heads/{_SRC_TAG}.zip",
    f"https://github.com/index-tts/index-tts/archive/refs/heads/{_SRC_TAG}.zip",
]


def venv_dir(data_dir: Path) -> Path:
    return data_dir / "runtimes" / "indextts-venv"


def status(data_dir: Path) -> dict[str, Any]:
    """installed = venv 存在且 import 自检通过（目录在但坏=未装完，可重装修复）。"""

    venv = venv_dir(data_dir)
    py = venv / "Scripts" / "python.exe"
    if not py.is_file():
        return {"installed": False, "dir": str(venv)}
    try:
        probe = subprocess.run(  # noqa: S603 - 固定解释器固定参数
            [str(py), "-c", "import indextts, torch"],
            capture_output=True, timeout=90, creationflags=_NO_WINDOW, check=False,
        )
        return {"installed": probe.returncode == 0, "dir": str(venv)}
    except (OSError, subprocess.TimeoutExpired):
        return {"installed": False, "dir": str(venv)}


def install(
    data_dir: Path,
    *,
    cancel: threading.Event,
    on_progress: Any | None = None,
) -> None:
    def _pct(value: float, stage: str) -> None:
        if on_progress is not None:
            on_progress(value, stage)

    def _check_cancel() -> None:
        if cancel.is_set():
            raise RuntimeError("已取消")

    runtimes = data_dir / "runtimes"
    runtimes.mkdir(parents=True, exist_ok=True)

    # ① uv.exe（~17MB 单文件；已存在跳过）
    uv = runtimes / "uv.exe"
    if not uv.is_file():
        _pct(2, "下载 uv 引导器")
        _fetch_first(_UV_SOURCES, runtimes / "uv.zip", 18 * 1024 * 1024, cancel)
        with zipfile.ZipFile(runtimes / "uv.zip") as zf:
            for item in zf.namelist():
                if item.endswith("uv.exe"):
                    uv.write_bytes(zf.read(item))
                    break
        (runtimes / "uv.zip").unlink(missing_ok=True)
        if not uv.is_file():
            raise RuntimeError("uv.exe 解包失败")
    _check_cancel()

    # ② venv + 独立 Python 3.11（uv 自动下载，国内镜像）
    venv = venv_dir(data_dir)
    py = venv / "Scripts" / "python.exe"
    if not py.is_file():
        _pct(8, "创建 Python 3.11 运行环境（首次含解释器下载）")
        _run_uv(uv, runtimes, "venv", str(venv), "--python", "3.11")
    _check_cancel()

    # ③ torch：有可用 N 卡走 cu128（GPU 大版），否则 CPU 轮（省 4GB）
    probe = subprocess.run(  # noqa: S603 - 固定解释器固定参数
        [str(py), "-c",
         "import torch;b=torch.cuda.is_available();"
         "print('gpu' if b and (torch.ones(4,device='cuda')*2).sum().item() else 'cpu')"],
        capture_output=True, text=True, timeout=120, creationflags=_NO_WINDOW, check=False,
    )
    gpu_ok = probe.stdout.strip().endswith("gpu")
    _pct(20, f"安装 torch（{'CUDA 12.8 变体' if gpu_ok else 'CPU 变体'}，约 0.2-2.5GB）")
    if gpu_ok:
        _run_uv(uv, venv, "pip", "install", *_TORCH_CPU, "--index-url", _TORCH_INDEX)
    else:
        _run_uv(uv, venv, "pip", "install", *_TORCH_CPU, "--index-url", _PYPI_MIRROR)
    _check_cancel()

    # ④ 其余依赖（清华镜像）
    _pct(60, "安装推理依赖（transformers 4.52 等 17 项）")
    _run_uv(uv, venv, "pip", "install", *_DEPS, "--index-url", _PYPI_MIRROR)
    _check_cancel()

    # ⑤ 源码 zip（免 git 依赖）→ --no-deps 安装
    src_root = runtimes / "indextts-src"
    if not (src_root / "pyproject.toml").is_file():
        _pct(88, "获取 IndexTTS 源码")
        _fetch_first(_SRC_SOURCES, runtimes / "indextts-src.zip", 25 * 1024 * 1024, cancel)
        with zipfile.ZipFile(runtimes / "indextts-src.zip") as zf:
            zf.extractall(runtimes / "indextts-src-tmp")
        inner = next((runtimes / "indextts-src-tmp").iterdir())
        shutil.move(str(inner), str(src_root))
        shutil.rmtree(runtimes / "indextts-src-tmp", ignore_errors=True)
        (runtimes / "indextts-src.zip").unlink(missing_ok=True)
    _pct(94, "安装源码（可编辑模式）")
    _run_uv(uv, venv, "pip", "install", "--no-deps", "-e", str(src_root))
    _check_cancel()

    # ⑥ 自检
    _pct(98, "自检（首次 import 较慢）")
    if not status(data_dir)["installed"]:
        raise RuntimeError("自检失败：venv 已建但 indextts 导入异常，可重试修复")
    _pct(100, "完成")


def _run_uv(uv: Path, venv: Path, *args: str) -> None:
    cmd = [str(uv), *args]
    env = {**os.environ, **_UV_ENV}
    if args and args[0] == "pip":
        cmd = [str(uv), "pip", "--python", str(venv / "Scripts" / "python.exe"), *args[1:]]
    result = subprocess.run(  # noqa: S603 - 固定二进制受控参数
        cmd, capture_output=True, text=True, timeout=1800,
        creationflags=_NO_WINDOW, env=env, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"uv {' '.join(args[:2])} 失败: {result.stderr[-300:]}")


def _fetch_first(sources: list[str], target: Path, size: int, cancel: threading.Event) -> None:
    last: Exception | None = None
    for url in sources:
        if cancel.is_set():
            raise RuntimeError("已取消")
        try:
            download_file(url, target, size, cancel=cancel)
            return
        except Exception as exc:  # noqa: BLE001 - 多源容错
            last = exc
    raise RuntimeError(f"全部源下载失败: {last}") from last
