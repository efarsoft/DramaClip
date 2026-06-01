"""
CosyVoice 运行时安装器（Phase 3.1）

目标：让普通用户通过“一键安装”就能让 CosyVoice 在隔离进程中可用。

功能：
- 创建专属 venv（推荐位置：pretrained_models/.venvs/cosyvoice3 或用户配置）
- 执行 FunAudioLLM/CosyVoice 官方推荐的安装流程
- 捕获常见错误（torch 版本、sox、git 等）并给出明确提示
- 支持进度回调

注意：Windows 上 venv + git clone + 编译依赖比较脆弱，此模块会尽量健壮处理并提供 fallback 建议。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Optional, Tuple

from loguru import logger


def get_cosyvoice_venv_dir() -> Path:
    """返回 CosyVoice 推荐的专属 venv 目录。"""
    # 优先放在 pretrained_models 下，便于和模型一起管理
    base = Path("pretrained_models") / ".venvs" / "cosyvoice3"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_cosyvoice_python() -> Optional[Path]:
    """返回隔离 venv 中的 python 路径（如果存在）。"""
    venv = get_cosyvoice_venv_dir()
    if sys.platform == "win32":
        py = venv / "Scripts" / "python.exe"
    else:
        py = venv / "bin" / "python"

    return py if py.exists() else None


def is_cosyvoice_package_available(python_path: Optional[Path] = None) -> bool:
    """检查指定 python 环境中是否能 import cosyvoice。"""
    if python_path is None:
        python_path = get_cosyvoice_python()
    if not python_path or not python_path.exists():
        return False

    try:
        result = subprocess.run(
            [str(python_path), "-c", "import cosyvoice; print('OK')"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return "OK" in result.stdout
    except Exception:
        return False


def is_runtime_ready() -> Tuple[bool, str]:
    """
    返回 (是否就绪, 提示信息)
    就绪条件：
    1. 有专属 python
    2. 能 import cosyvoice
    3. 模型目录存在（可选，交给 sidecar 判断）
    """
    py = get_cosyvoice_python()
    if not py:
        return False, "未找到 CosyVoice 隔离运行时。请点击“一键安装运行时”"

    if not is_cosyvoice_package_available(py):
        return False, "CosyVoice 包未在隔离环境中安装。请重新运行安装"

    # 额外检查常见 Windows 依赖 (sox)
    if sys.platform == "win32":
        try:
            subprocess.run(["sox", "--version"], capture_output=True, timeout=5)
        except Exception:
            return False, "运行时已安装，但缺少 sox（Windows 常见问题）。请安装 sox 并加入 PATH 后重试。"

    return True, "CosyVoice 隔离运行时已就绪"


def install_cosyvoice_runtime(
    progress_callback: Optional[Callable[[int, str], None]] = None,
    cancel_flag: Optional[threading.Event] = None,
) -> bool:
    """
    一键安装 CosyVoice 运行时。

    步骤（参考 FunAudioLLM/CosyVoice 官方推荐）：
    1. 创建 venv
    2. 升级 pip / wheel
    3. git clone --recursive CosyVoice（如果不存在）
    4. cd CosyVoice && pip install -r requirements.txt
    5. 额外处理常见 Windows 问题（sox、torch 等）

    返回是否成功。
    """
    if cancel_flag is None:
        cancel_flag = threading.Event()

    venv_dir = get_cosyvoice_venv_dir()
    py_path = get_cosyvoice_python()

    def report(pct: int, msg: str):
        logger.info(f"[CosyVoice Installer] {pct}% - {msg}")
        if progress_callback:
            progress_callback(pct, msg)

    if py_path and is_cosyvoice_package_available(py_path):
        report(100, "运行时已存在且可用")
        return True

    try:
        report(5, "准备创建隔离虚拟环境...")

        # 1. 创建 venv（如果不存在）
        if not py_path or not py_path.exists():
            report(10, "正在创建 venv ...")
            venv_parent = venv_dir.parent
            venv_parent.mkdir(parents=True, exist_ok=True)

            subprocess.check_call(
                [sys.executable, "-m", "venv", str(venv_dir)],
                timeout=120
            )
            py_path = get_cosyvoice_python()
            if not py_path:
                raise RuntimeError("venv 创建失败")

        report(25, "venv 创建完成，正在升级 pip...")

        # 2. 升级 pip
        subprocess.check_call(
            [str(py_path), "-m", "pip", "install", "--upgrade", "pip", "wheel", "setuptools"],
            timeout=180
        )

        report(40, "pip 升级完成，正在准备 CosyVoice 源码...")

        # 3. Clone CosyVoice（如果没有）
        cosyvoice_src = Path("pretrained_models") / "CosyVoice"
        if not (cosyvoice_src / ".git").exists():
            if cancel_flag.is_set():
                return False

            report(45, "正在 git clone CosyVoice（可能需要几分钟）...")
            if cosyvoice_src.exists():
                shutil.rmtree(cosyvoice_src, ignore_errors=True)

            subprocess.check_call(
                ["git", "clone", "--recursive", "https://github.com/FunAudioLLM/CosyVoice.git", str(cosyvoice_src)],
                timeout=300
            )

        report(65, "源码准备完成，正在安装依赖（这步最容易失败）...")

        # 4. 安装 requirements
        req_file = cosyvoice_src / "requirements.txt"
        if not req_file.exists():
            raise RuntimeError("未找到 requirements.txt，请手动检查 CosyVoice 仓库")

        # Windows 常见问题提示
        install_cmd = [
            str(py_path), "-m", "pip", "install",
            "-r", str(req_file),
            "--extra-index-url", "https://download.pytorch.org/whl/cu121"  # 尽量用 CUDA 12.1
        ]

        process = subprocess.Popen(
            install_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        last_pct = 65
        for line in iter(process.stdout.readline, ""):
            if cancel_flag.is_set():
                process.terminate()
                return False

            line = line.strip()
            if line:
                logger.debug(f"[CosyVoice pip] {line}")

                # 简单进度估算
                if "Installing" in line or "Collecting" in line:
                    last_pct = min(90, last_pct + 1)
                    report(last_pct, f"正在安装依赖：{line[:60]}...")

        ret = process.wait(timeout=600)
        if ret != 0:
            raise RuntimeError(f"pip install 失败，返回码 {ret}。常见原因：torch 版本冲突、缺少 sox、Visual Studio C++ Build Tools。")

        report(95, "依赖安装完成，正在最终验证...")

        # 5. 最终验证 + 简单测试
        if not is_cosyvoice_package_available(py_path):
            raise RuntimeError("安装后仍无法 import cosyvoice，请查看日志或手动安装。")

        # 尝试简单 import 测试（不加载模型）
        try:
            subprocess.check_call(
                [str(py_path), "-c", "import cosyvoice.cli.cosyvoice; print('CosyVoice import OK')"],
                timeout=30
            )
        except Exception as test_err:
            raise RuntimeError(f"依赖安装成功但 import 测试失败: {test_err}")

        report(100, "CosyVoice 隔离运行时安装成功！可用于 subprocess 模式。")
        return True

    except subprocess.TimeoutExpired:
        report(0, "安装超时，请检查网络或手动执行安装命令。")
        return False
    except Exception as e:
        error_msg = str(e)
        report(0, f"安装失败: {error_msg[:200]}")
        logger.error(f"CosyVoice runtime install failed: {e}")
        return False


def get_install_instructions() -> str:
    """返回给用户的详细手动安装指导（当自动安装失败时使用）。"""
    return (
        "自动安装失败时，请手动执行以下步骤（推荐在 PowerShell 以管理员身份运行）：\n\n"
        "1. 创建独立 venv：\n"
        "   python -m venv D:\\DramaClip\\pretrained_models\\.venvs\\cosyvoice3\n\n"
        "2. 激活：\n"
        "   .\\pretrained_models\\.venvs\\cosyvoice3\\Scripts\\Activate.ps1\n\n"
        "3. 安装 CosyVoice（关键步骤）：\n"
        "   git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git\n"
        "   cd CosyVoice\n"
        "   pip install -r requirements.txt\n\n"
        "4. Windows 常见问题解决（按顺序尝试）：\n"
        "   a. 缺少 sox（最常见）：\n"
        "      下载 https://sourceforge.net/projects/sox/files/sox/14.4.2/sox-14.4.2-win32.zip\n"
        "      解压后把 sox.exe 所在目录加入系统 PATH，重启终端\n"
        "   b. torch 版本冲突：\n"
        "      pip install torch==2.4.0+cu121 torchaudio==2.4.0+cu121 -f https://download.pytorch.org/whl/torch_stable.html\n"
        "   c. 编译错误：安装 Visual Studio Build Tools (C++ 工作负载)\n"
        "   d. 其他：尝试在激活的 venv 中运行：pip install --upgrade pip setuptools wheel\n\n"
        "5. 验证安装：\n"
        "   python -c \"import cosyvoice.cli.cosyvoice; print('SUCCESS')\"\n\n"
        "安装成功后，在 DramaClip 设置 → 模型管理 中选择“CosyVoice 3（进程隔离）”即可使用。"
    )
