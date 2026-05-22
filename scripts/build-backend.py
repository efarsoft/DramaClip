#!/usr/bin/env python3
"""
PyInstaller 打包脚本
将 Python 后端打包为 backend.exe
"""

import os
import sys
import shutil
from pathlib import Path
from loguru import logger

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def get_pyinstaller_cmd(
    dist_dir: Path,
    build_dir: Path,
    spec_file: Path = None
) -> list:
    src_dir = project_root / "app"

    # 优先使用项目虚拟环境 .venv 中的 pyinstaller 进行打包，避免污染或遗漏依赖
    pyinstaller_bin = "pyinstaller"
    venv_dir = project_root / ".venv"
    if sys.platform == "win32":
        venv_pyinstaller = venv_dir / "Scripts" / "pyinstaller.exe"
    else:
        venv_pyinstaller = venv_dir / "bin" / "pyinstaller"

    if venv_pyinstaller.exists():
        pyinstaller_bin = str(venv_pyinstaller)
        logger.info(f"Using project virtual environment pyinstaller: {pyinstaller_bin}")
    else:
        logger.warning("Project virtual environment pyinstaller not found, falling back to system 'pyinstaller'")

    cmd = [
        pyinstaller_bin,
        "--name", "backend",
        "--onefile",
        "--console",
        "--noconfirm",
        "--distpath", str(dist_dir),
        "--workpath", str(build_dir),
        "--specpath", str(spec_file) if spec_file else str(dist_dir),
        "--add-data", f"{src_dir};app",
    ]

    # 添加 resources 目录
    resources_dir = project_root / "resources"
    if resources_dir.exists():
        cmd.extend(["--add-data", f"{resources_dir};resources"])

    # 主入口
    cmd.append(str(src_dir / "backend_main.py"))

    return cmd


def build_backend():
    """执行打包"""
    dist_dir = project_root / "dist-backend"
    build_dir = project_root / "build"

    # 创建输出目录
    dist_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Building backend.exe to {dist_dir}")

    cmd = get_pyinstaller_cmd(dist_dir, build_dir)
    logger.info(f"Command: {' '.join(cmd)}")

    import subprocess
    result = subprocess.run(cmd, cwd=str(project_root))

    if result.returncode != 0:
        logger.error("Build failed!")
        return False

    # 复制 FFmpeg（如果有）
    resources_dir = project_root / "resources"
    ffmpeg_src = resources_dir / "ffmpeg.exe"
    if ffmpeg_src.exists():
        ffmpeg_dst = dist_dir / "resources" / "ffmpeg.exe"
        ffmpeg_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ffmpeg_src, ffmpeg_dst)
        logger.info(f"Copied FFmpeg to {ffmpeg_dst}")

    logger.info("Build completed!")
    return True


if __name__ == "__main__":
    build_backend()
