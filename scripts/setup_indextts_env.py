"""IndexTTS-2.5 运行环境引导：在数据目录下建隔离 venv（Python 3.10/3.11）。

主程序 Python 3.13 与上游 indextts 的 `<3.12` 约束不可调和，此脚本按
docs/design/tts-asr-research 的隔离方案重建全套运行时：

    .venv/Scripts/python scripts/setup_indextts_env.py

步骤：定位 3.11/3.10 解释器（py 启动器 → PATH）→ venv 到
<runtimes>/indextts-venv → pin 版本依赖（torch cu128 优先 CPU 兜底，
镜像加速）→ clone 上游源码（--no-deps 安装）→ import 自检。
任何一步失败打印可操作的下一步，退出码非零。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _default_data_dir() -> str:
    base = os.environ.get("DRAMACLIP_DATA_DIR")
    if base:
        return base
    appdata = os.environ.get("APPDATA")
    if appdata:
        return str(Path(appdata) / "DramaClip")
    return str(Path.home() / ".local" / "share" / "dramaclip")

RUNTIMES_DIR = Path(_default_data_dir()) / "runtimes"
VENV_DIR = RUNTIMES_DIR / "indextts-venv"
SRC_DIR = RUNTIMES_DIR / "indextts-src"

PYPI_MIRROR = os.environ.get("DRAMACLIP_PYPI_MIRROR", "https://pypi.tuna.tsinghua.edu.cn/simple")
PYTORCH_INDEX = "https://download.pytorch.org/whl/cu128"
PIP_CORE = ["torch==2.8.0", "torchaudio==2.8.0"]
PIP_DEPS = [
    "transformers==4.52.1",
    "omegaconf",
    "accelerate",
    "munch",
    "einops",
    "descript-audiotools",
    "json5",
    "wetext",
    "cn2an",
    "jieba",
    "numba",
    "openai-whisper",
    "sentencepiece",
    "fugashi",
    "unidic-lite",
    "g2p-en",
    "modelscope==1.27.0",
]
CLONE_URLS = [
    "https://gitclone.com/github.com/index-tts/index-tts.git",
    "https://github.com/index-tts/index-tts.git",
]




def _find_python311() -> str | None:
    for tag in ("-3.11", "-3.10"):
        try:
            probe = subprocess.run(
                ["py", tag, "-c", "print(1)"], capture_output=True, text=True, timeout=15, check=False,
            )
            if probe.returncode == 0:
                where = subprocess.run(
                    ["py", tag, "-c", "import sys; print(sys.executable)"],
                    capture_output=True, text=True, timeout=15, check=False,
                )
                path = where.stdout.strip()
                if path:
                    return path
        except (OSError, subprocess.TimeoutExpired):
            continue
    return shutil.which("python3.11") or shutil.which("python3.10")


def _run(cmd: list[str], **kw: object) -> int:
    print("[setup]", " ".join(cmd[:4]), "...", flush=True)
    return subprocess.run(cmd, check=False, **kw).returncode  # type: ignore[arg-type]


def main() -> int:
    print(f"目标 venv: {VENV_DIR}")
    if VENV_DIR.exists():
        print("已存在——如需重建请先删除该目录")
        return 0

    base = _find_python311()
    if base is None:
        print(
            "未找到 Python 3.10/3.11：请安装（https://www.python.org/downloads/release/python-3119/）"
            "后重试，或用 uv：uv python install 3.11"
        )
        return 1
    print(f"解释器: {base}")

    RUNTIMES_DIR.mkdir(parents=True, exist_ok=True)
    venv.create(VENV_DIR, executable=base, with_pip=True)
    py = str(VENV_DIR / "Scripts" / "python.exe")

    code = _run([py, "-m", "pip", "install", *PIP_CORE, "--index-url", PYTORCH_INDEX, "--no-deps"])
    if code != 0:
        code = _run([py, "-m", "pip", "install", *PIP_CORE, "--index-url", PYPI_MIRROR.replace("simple", "pytorch-whl-cpu") if False else PYPI_MIRROR])
        if code != 0:
            print("torch 安装失败（网络/镜像），检查后重试")
            return 1
    _run([py, "-m", "pip", "install", *PIP_DEPS, "-i", PYPI_MIRROR])

    if not SRC_DIR.exists():
        for url in CLONE_URLS:
            if _run(["git", "clone", "--depth", "1", url, str(SRC_DIR)]) == 0:
                break
        else:
            print("源码 clone 失败：手动执行 git clone https://github.com/index-tts/index-tts.git 放到", SRC_DIR)
            return 1
    _run([py, "-m", "pip", "install", "--no-deps", "-e", str(SRC_DIR)])

    probe = subprocess.run(
        [py, "-c", "import indextts, torch; print('ready', torch.__version__)"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    if probe.returncode != 0:
        print("自检失败：", probe.stderr[-400:])
        return 1
    print("IndexTTS 运行环境就绪：", probe.stdout.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
