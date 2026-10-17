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
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_DIR = REPO_ROOT / "service"
BUILD_DIR = REPO_ROOT / "build" / "service"
DIST_DIR = BUILD_DIR / "dist" / "dramaclip-service"
OUTPUT_DIR = REPO_ROOT / "resources" / "dramaclip-service"
EXE = DIST_DIR / "dramaclip-service.exe"

# PYZ 断言的禁入清单（E-2）：主包零 torch 是「本地智能运行环境按需装」的前提，
# 谁把这个假设打破谁就把 2.5GB+ 带回安装包（2026-10-16 cu126 事故包实测 4.8GB）。
_BANNED_PREFIXES = ("torch", "transformers", "funasr", "kokoro", "misaki")

# 重依赖随包清单（E-2 起 torch 系移出：funasr/kokoro 的 torch 依赖在本地智能
# 运行环境 tts-venv 的 worker 进程里执行，主包零 torch）。懒加载可被字节码扫描
# 发现——transcriber/kokoro 的进程内回退分支仍写着 import torch/funasr/kokoro，
# 靠下方 EXCLUDES 压制（excludes 优先级高于扫描发现）。
HIDDEN_IMPORTS = [
    "faster_whisper",
    "ctranslate2",
    "scenedetect",
    "librosa",
    "soundfile",
    "scipy",
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
    # E-2 torch 系：主包零 torch（构建机 venv 装没装都不进包），运行时走 tts-venv
    "torch",
    "torchaudio",
    "torchvision",
    "transformers",
    "funasr",
    "kaldiio",
    "kokoro",
    "misaki",
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

    # E-2 起构建 venv 里有没有 torch、是什么变体都无关紧要（EXCLUDES 压制）——
    # 旧的「禁 CUDA torch 预检」退役；发布守卫改由产物 PYZ 断言承担（见下方）。

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
    # jieba 词典数据：热词挖掘在主进程用（misaki/kokoro/num2words 已随 E-2 移出主包）
    cmd += ["--collect-data", "jieba"]
    if args.cuda:
        # CUDA 变体：运行库随包（用户只需 NVIDIA 驱动）；ctranslate2 自动启用 GPU
        for module in ("nvidia.cublas", "nvidia.cudnn"):
            cmd += ["--collect-all", module]
    cmd.append(str(entry))

    print("[build-service] PyInstaller 开始…")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print("[build-service] PyInstaller 失败", file=sys.stderr)
        return result.returncode

    rc = _assert_pyz_free_of_torch()
    if rc != 0:
        return rc

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    shutil.copytree(DIST_DIR, OUTPUT_DIR)

    total = sum(f.stat().st_size for f in OUTPUT_DIR.rglob("*") if f.is_file())
    print(f"[build-service] 完成: {OUTPUT_DIR}")
    print(f"[build-service] 体积: {total / 1024 / 1024:.0f} MB")
    return 0


def _assert_pyz_free_of_torch() -> int:
    """产物断言：PYZ TOC 不得含 torch 系模块（专项 C 的 ZlibArchiveReader 方法论）。

    PYZ 嵌在 exe 的 CArchive 里（'PYZ.pyz' 条目）而非裸文件——两段式提取后再读。
    读取失败按构建失败处理：断言读不出来就等于没有断言，静默跳过会让下一次
    依赖准入的失误直接溜进发布包。
    """
    from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

    try:
        arch = CArchiveReader(str(EXE))
        pyz_names = [k for k, v in arch.toc.items() if v[-1] in ("z", "Z") or "pyz" in k.lower()]
        if not pyz_names:
            raise RuntimeError("CArchive 里找不到 PYZ 条目")
        data = arch.extract(pyz_names[0])
        with tempfile.TemporaryDirectory() as tmp:
            pyz = Path(tmp) / "PYZ.pyz"
            pyz.write_bytes(data)
            toc = ZlibArchiveReader(str(pyz)).toc
    except Exception as exc:  # noqa: BLE001 - 读取失败不许静默放行
        print(f"[build-service] PYZ 断言无法执行（{exc}），拒绝发布", file=sys.stderr)
        return 2
    hits = sorted(
        name for name in toc if name.split(".")[0] in _BANNED_PREFIXES
    )
    if hits:
        print(
            f"[build-service] 拒绝发布：PYZ 内发现 torch 系模块 {hits[:8]}"
            f"（共 {len(hits)} 个）——检查 EXCLUDES 是否被绕过",
            file=sys.stderr,
        )
        return 2
    print(f"[build-service] PYZ 断言通过：产物零 torch 系（TOC {len(toc)} 项）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
