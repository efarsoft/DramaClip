"""配乐生成运行时引导：music-venv（Python 3.11 + torch 2.7.1 + acestep 源码包）。

与 tts_runtime 同一套 uv 流程，但**独立 venv**：上游 pyproject 把 Windows torch
钉在 2.7.1+cu128（tts-venv 是 2.8.0），且依赖集（diffusers/gradio/torchao/
nano-vllm 路径依赖）与双栈 TTS 的 pin 有交集冲突风险——隔离是唯一稳妥解。

流程（阶段→进度）：uv.exe 复用/下载(0-5) → venv 创建(5-15) → torch 2.7.1
变体(15-45，GPU 探测定 cu128/CPU) → acestep 源码 zip（钉 rev，MIT）(45-55) →
pip install 源码包（依赖自解析，torch 已在位不会重复拉）(55-90) → import
自检(90-100)。可取消，可重入（已存在阶段跳过）。

上游无 PyPI 包：安装源 = GitHub 归档 zip（无 submodule，nano-vllm 内嵌在
acestep/third_parts/，归档完整——2026-10-24 实测 36 个文件）。zip 字节数按钉
rev 固定（download_file 的期望体积是精确匹配校验）。
"""

from __future__ import annotations

import threading
import zipfile
from pathlib import Path
from typing import Any

from dramaclip.infra.model_manager import tts_runtime

# 与 tts_runtime 共用的常量抄本（它已贴近 800 行门禁不再扩；这边只取所需三件）
_PYPI_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
_GH_PROXY = "https://gh-proxy.com/https://github.com"
_TORCH_INDEX = "https://download.pytorch.org/whl/cu128"
# 上游 pyproject 的 Windows torch pin（2026-10-24 量）：2.7.1+cu128 系
_MUSIC_TORCH = ["torch==2.7.1", "torchaudio==2.7.1", "torchvision==0.22.1"]

# 源码钉 revision：zip 字节数按 rev 固定（9148700，2026-10-24 codeload 实测）。
_ACESTEP_REV = "ca1e85fe9430179831e6bc6be790c332190a3866"
_ACESTEP_ZIP_SIZE = 9148700
_ACESTEP_SOURCES = [
    f"{_GH_PROXY}/ace-step/ACE-Step-1.5/archive/{_ACESTEP_REV}.zip",
    f"https://github.com/ace-step/ACE-Step-1.5/archive/{_ACESTEP_REV}.zip",
]
# uv 引导器与 tts_runtime 同一份（runtimes/uv.exe 已在则复用；首装两路等价）。
_UV_SOURCES = tts_runtime._UV_SOURCES
_UV_ZIP_SIZE = tts_runtime._UV_ZIP_SIZE
_UV_ENV = tts_runtime._UV_ENV


def venv_dir(data_dir: Path) -> Path:
    return data_dir / "runtimes" / "music-venv"


def venv_python(data_dir: Path) -> Path:
    return venv_dir(data_dir) / "Scripts" / "python.exe"


def src_dir(data_dir: Path) -> Path:
    return data_dir / "runtimes" / "acestep-src"


def installed(data_dir: Path) -> bool:
    """零探针安装判据：venv 解释器 + acestep 包目录在场（纯文件检查）。"""
    venv = venv_dir(data_dir)
    if not venv_python(data_dir).is_file():
        return False
    return (venv / "Lib" / "site-packages" / "acestep" / "__init__.py").is_file()


def _variant_marker(data_dir: Path) -> Path:
    return venv_dir(data_dir).parent / "music-venv.torch-variant"


def torch_variant(data_dir: Path) -> str:
    """music-venv 里 torch 的变体：cuda / cpu / unknown（装的时候选了哪条轮子）。"""
    try:
        raw = _variant_marker(data_dir).read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    return raw if raw in ("cuda", "cpu") else "unknown"


def status(data_dir: Path) -> dict[str, Any]:
    """运行时安装态（零探针：文件在场即装好，真坏了由 worker 启动失败如实报错）。"""
    return {
        "installed": installed(data_dir),
        "dir": str(venv_dir(data_dir)),
        "torch_variant": torch_variant(data_dir),
    }


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

    # ① uv.exe：与 tts_runtime 共用一份（已在则零成本复用）
    uv = runtimes / "uv.exe"
    if not uv.is_file():
        _pct(2, "下载 uv 引导器")
        tts_runtime._fetch_first(_UV_SOURCES, runtimes / "uv.zip", _UV_ZIP_SIZE, cancel)
        with zipfile.ZipFile(runtimes / "uv.zip") as zf:
            for item in zf.namelist():
                if item.endswith("uv.exe"):
                    uv.write_bytes(zf.read(item))
                    break
        (runtimes / "uv.zip").unlink(missing_ok=True)
        if not uv.is_file():
            raise RuntimeError("uv.exe 解包失败")
    _check_cancel()

    # ② venv + 独立 Python 3.11（上游 requires-python >=3.11,<3.13）
    venv = venv_dir(data_dir)
    py = venv / "Scripts" / "python.exe"
    if not py.is_file():
        _pct(8, "创建配乐运行环境（首次含解释器下载）")
        tts_runtime._run_uv(uv, venv, "venv", str(venv), "--python", "3.11")
    _check_cancel()

    # ③ torch：变体判据与双栈同一份；xpu 主机（Intel Arc/Ultra）降装 CPU 轮——
    #    ACE-Step 在 XPU 后端的算子覆盖未验证，不给用户拉一份用不上的 2.5GB 轮
    variant = tts_runtime._gpu_variant()
    if variant == "xpu":
        print("[music-runtime] XPU 主机：ACE-Step 未验证，music-venv 装 CPU 轮")
        variant = "cpu"
    variant_label = "CUDA 12.8" if variant == "cuda" else "CPU"
    _pct(18, f"安装 torch（{variant_label} 变体，约 0.2-2.5GB）")
    _install_torch(uv, venv, variant)
    _check_cancel()

    # ④ acestep 源码（钉 rev；归档完整已实测）+ pip 安装（依赖自解析；
    #    torch 已在位，解析器不会重复拉——先装 torch 是变体可控的前提）
    src = src_dir(data_dir)
    if not (src / "pyproject.toml").is_file():
        _pct(48, "获取 ACE-Step 源码（MIT，钉 revision）")
        tts_runtime._fetch_first(
            _ACESTEP_SOURCES, runtimes / "acestep-src.zip", _ACESTEP_ZIP_SIZE, cancel,
        )
        tts_runtime._extract_zip_stripped(runtimes / "acestep-src.zip", src)
        (runtimes / "acestep-src.zip").unlink(missing_ok=True)
    _check_cancel()
    if not installed(data_dir):
        _pct(58, "安装 acestep 及依赖（gradio/diffusers 等，约 1-2GB）")
        tts_runtime._run_uv(
            uv, venv, "pip", "install", str(src), "--index-url", _PYPI_MIRROR,
        )
    _check_cancel()

    # ⑤ 自检：包可导入即交付（生成能力由 worker 首次加载模型时诚实裁决）
    _pct(94, "自检（首次 import 较慢）")
    if not tts_runtime._venv_imports_ok(py, ("acestep",)):
        raise RuntimeError("自检失败：acestep 导入异常（配乐生成），可重试修复")
    _variant_marker(data_dir).write_text(variant, encoding="utf-8")
    _pct(100, "完成")


def _install_torch(uv: Path, venv: Path, variant: str) -> None:
    """torch 按变体安装（与 tts_runtime._install_torch 同策略，pin 换成上游 2.7.1 系）。"""
    if variant == "cpu":
        tts_runtime._run_uv(uv, venv, "pip", "install", *_MUSIC_TORCH, "--index-url", _PYPI_MIRROR)
        return
    mirror_dir = "https://mirrors.aliyun.com/pytorch-wheels/cu128/"
    attempts: list[tuple[str, list[str]]] = [
        ("官方 cu 源", ["pip", "install", *_MUSIC_TORCH, "--index-url", _TORCH_INDEX]),
        (
            "阿里镜像",
            [
                "pip", "install", *_MUSIC_TORCH,
                "--find-links", mirror_dir, "--index-url", _PYPI_MIRROR,
            ],
        ),
    ]
    last: Exception | None = None
    for label, args in attempts:
        try:
            tts_runtime._run_uv(uv, venv, *args)
            return
        except RuntimeError as exc:
            last = exc
            print(f"[music-runtime] torch {variant} 轮 {label} 失败，尝试下一来源")
    raise RuntimeError(f"torch {variant} 轮全部来源失败: {last}")
