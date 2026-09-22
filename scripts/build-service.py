"""PyInstaller sidecar 构建：service → resources/dramaclip-service/（onedir）。

用法：.venv/Scripts/python.exe scripts/build-service.py
产物：resources/dramaclip-service/dramaclip-service.exe（gitignored，
由 electron-builder extraResources 随安装包分发；主进程打包模式经
DRAMACLIP_RESOURCES_DIR 注入该目录）。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_DIR = REPO_ROOT / "service"
BUILD_DIR = REPO_ROOT / "build" / "service"
DIST_DIR = BUILD_DIR / "dist" / "dramaclip-service"
OUTPUT_DIR = REPO_ROOT / "resources" / "dramaclip-service"

# 重依赖全部随包（懒加载可被字节码扫描发现，这里显式声明防止漏收）
HIDDEN_IMPORTS = [
    "faster_whisper",
    "ctranslate2",
    "scenedetect",
    "librosa",
    "soundfile",
    "scipy",
    "torch",
    "transformers",
    "kokoro",
    "misaki",
    "edge_tts",
]

# 体积排除表（docs/00 ADR：Python 打包体积→排除表）
# 注：pip/setuptools/wheel 不可排除——与 PyInstaller 运行时钩子冲突（ValueError already imported）
EXCLUDES = [
    "tkinter",
    "pytest",
    "ruff",
    "mypy",
    "IPython",
    "matplotlib",
    "PyQt5",
    "PySide6",
    "unittest",
    "pydoc_data",
]

ENTRY = """\
from dramaclip.__main__ import main

raise SystemExit(main())
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 DramaClip Python sidecar")
    parser.add_argument(
        "--cuda",
        action="store_true",
        help="收集 NVIDIA CUDA 运行库（nvidia-cublas-cu12 / nvidia-cudnn-cu12，需先在 venv 安装；体积 +~700MB）",
    )
    args = parser.parse_args()

    entry = BUILD_DIR / "sidecar_entry.py"
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    entry.write_text(ENTRY, encoding="utf-8")

    cmd: list[str] = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        "dramaclip-service",
        "--paths",
        str(SERVICE_DIR),
        "--distpath",
        str(BUILD_DIR / "dist"),
        "--workpath",
        str(BUILD_DIR / "work"),
        "--specpath",
        str(BUILD_DIR),
    ]
    for module in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", module]
    for module in EXCLUDES:
        cmd += ["--exclude-module", module]
    # 汉化/音素化数据 + 包内迁移 SQL（PyInstaller 静态分析收不全）
    cmd += ["--collect-data", "dramaclip"]
    # IndexTTS worker 源码：从未被 import（子进程按路径执行），静态分析不会收集；
    # 落位 _internal/dramaclip/engines/tts/workers/ 与适配器 __file__ 相对寻址吻合
    workers_src = SERVICE_DIR / "dramaclip" / "engines" / "tts" / "workers"
    if workers_src.is_dir():
        cmd += ["--add-data", f"{workers_src};dramaclip/engines/tts/workers"]
    for module in ("misaki", "kokoro", "jieba", "num2words"):
        cmd += ["--collect-data", module]
    if args.cuda:
        # CUDA 变体：运行库随包（用户只需 NVIDIA 驱动）；ctranslate2 自动启用 GPU
        for module in ("nvidia.cublas", "nvidia.cudnn"):
            cmd += ["--collect-all", module]
    cmd.append(str(entry))

    print("[build-service] PyInstaller 开始（含 torch，需数分钟）…")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print("[build-service] PyInstaller 失败", file=sys.stderr)
        return result.returncode

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    shutil.copytree(DIST_DIR, OUTPUT_DIR)

    total = sum(f.stat().st_size for f in OUTPUT_DIR.rglob("*") if f.is_file())
    print(f"[build-service] 完成: {OUTPUT_DIR}")
    print(f"[build-service] 体积: {total / 1024 / 1024:.0f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
