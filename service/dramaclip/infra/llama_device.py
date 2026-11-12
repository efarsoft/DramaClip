"""llama-server 的 CUDA 设备枚举与选卡：本地视觉轨算力解析的唯一入口。

设备清单以 ``llama-server --list-devices`` 为准——它反映「这份构建在这台机器上
真能初始化的后端」：CPU 构建恒为空，CUDA 构建缺运行库 DLL 时也为空。比「显卡在场」
或「文件在场」都诚实，所以选卡不看能力表，只看这份清单。

只认 CUDA 设备。依据是 2026-11-12 真机对测（Quadro M4000 算力 5.2，Qwen3-VL-4B，
四图一组、上下文 12288）：CPU ≈215s / Vulkan ≈100s / CUDA ≈54s 每组（冷态；该卡
散热差，持续满载过热降频后 CUDA 稳态约 90s，仍近 CPU 一半）；同机 RX 5500 XT
走 Vulkan ≈200s，与 CPU 持平。构建带 Vulkan 后端时清单里会有 Vulkan
设备，这里不选它——多显卡默认平摊会被慢卡拖住，持平的卸载也不值一次显存占用。
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from dramaclip.infra.model_manager import cuda_runtime

CUDA_BACKEND_DLL = "ggml-cuda.dll"
SERVER_REL = Path("tools") / "llama.cpp" / "llama-server.exe"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_LIST_TIMEOUT_S = 60.0
# 权重之外的显存余量：KV（上下文 12288）+ 计算缓冲 + 视觉编码缓冲。4B 实测占用
# 5.2GB = 权重 2.95GB + 2.25GB，取整留边；估低了的代价是一次启动失败后如实回退。
_CONTEXT_HEADROOM_MB = 2560
_DEVICE_LINE = re.compile(
    r"^\s*(CUDA\d+):\s*(.+?)\s*\((\d+)\s*MiB,\s*(\d+)\s*MiB free\)\s*$"
)


def server_exe(data_dir: Path) -> Path:
    """视觉轨 llama-server 的落位（与 engines/vision.runtime 同一约定）。"""
    return data_dir / SERVER_REL


@dataclass(frozen=True)
class CudaDevice:
    device_id: str  # llama-server 的设备名（--device 的取值），如 CUDA0
    name: str
    total_mb: int
    free_mb: int


@dataclass(frozen=True)
class Choice:
    """选卡结论：device 为空即落 CPU，reason 说清为什么。"""

    device: CudaDevice | None
    reason: str = ""


def parse_devices(text: str) -> list[CudaDevice]:
    """解析 --list-devices 输出里的 CUDA 设备行；其余后端与噪声行一律跳过。"""
    devices: list[CudaDevice] = []
    for line in text.splitlines():
        match = _DEVICE_LINE.match(line)
        if match is None:
            continue
        devices.append(
            CudaDevice(
                device_id=match.group(1),
                name=match.group(2),
                total_mb=int(match.group(3)),
                free_mb=int(match.group(4)),
            )
        )
    return devices


def runtime_env(data_dir: Path | None) -> dict[str, str] | None:
    """带 CUDA 运行库目录的子进程环境；None = 原样继承。

    服务启动时已往进程 PATH 注入过一次，这里再显式前置：运行库是服务起来之后
    才装的、或调用方不是服务进程（命令行/网关）时，子进程照样找得到 DLL。
    """
    if data_dir is None:
        return None
    dirs = [str(d) for d in cuda_runtime.dll_dirs(data_dir)]
    if not dirs:
        return None
    return {**os.environ, "PATH": os.pathsep.join([*dirs, os.environ.get("PATH", "")])}


def list_cuda_devices(exe: Path, env: dict[str, str] | None = None) -> list[CudaDevice]:
    """跑一次 --list-devices。起不来/超时/老构建不认该参数都按空清单处理——
    调用方据此落 CPU 并留原因，探测失败不该拖垮视觉轨。"""
    try:
        result = subprocess.run(  # noqa: S603 - 固定二进制固定参数
            [str(exe), "--list-devices"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_LIST_TIMEOUT_S, creationflags=_NO_WINDOW, check=False, env=env,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    return parse_devices(f"{result.stdout}\n{result.stderr}")


def required_mb(model: Path, mmproj: Path) -> int:
    """整模型卸载的显存需求估算：两份权重文件 + 上下文余量。"""
    weights = sum(p.stat().st_size for p in (model, mmproj) if p.is_file())
    return weights // (1024 * 1024) + _CONTEXT_HEADROOM_MB


def has_cuda_build(exe: Path) -> bool:
    """llama-server 旁是否带 CUDA 后端（纯文件判据，能力表等高频路径用）。"""
    return (exe.parent / CUDA_BACKEND_DLL).is_file()


def choose(
    devices: list[CudaDevice], need_mb: int, *, explicit: bool, cuda_build: bool
) -> Choice:
    """空闲显存最多的 CUDA 设备；auto 下余量不够就不上。

    显式 cuda（``explicit``）不做余量把关：那是用户的承诺，装不下由启动失败如实报错。
    """
    if not devices:
        if cuda_build:
            return Choice(None, "CUDA 构建未枚举到设备（CUDA 运行库未安装，或驱动不支持 CUDA 12）")
        return Choice(None, "llama.cpp 为 CPU 构建（视觉模型 CUDA 构建资产未入库）")
    best = max(devices, key=lambda d: d.free_mb)
    if not explicit and best.free_mb < need_mb:
        return Choice(
            None,
            f"显存余量不足：需约 {need_mb / 1024:.1f}GB，"
            f"{best.name} 空闲 {best.free_mb / 1024:.1f}GB",
        )
    return Choice(best)
