"""设备分档与引擎能力结论：探测快照 → 档位 / 各引擎可用性 / 驱动引导。

纯函数，供 system.health 现算（便宜且无 IO）。分档判据只看硬件事实
（显存、驱动支持的 CUDA 上限），「运行时装没装」是另一层状态，由
cuda_runtime.status 提供，profile 里合成为 ready 结论。

档位阈值按本项目各负载的实测显存需求定：whisper large-v3（fp16 ~5GB）、
IndexTTS-2.5（registry notes 4GB+）、本地视觉轨三档（2B/4B/8B 权重
fp16 估算 6/8/16GB，首跑以 verify 为准）。
"""

from __future__ import annotations

from typing import Any

# cuda_runtime 钉 cu12：CUDA 12.x 官方矩阵的 Windows 最低驱动（551.61，取整 551）
_MIN_DRIVER_MAJOR = 551
_DRIVER_URL = "https://www.nvidia.cn/drivers/lookup/"

_TIER_LABELS = {
    "none": "未检测到 NVIDIA 显卡",
    "low": "入门（<6GB 显存）",
    "entry": "标准（6-11GB 显存）",
    "mid": "主力（12-19GB 显存）",
    "high": "高配（20GB+ 显存）",
}


def tier_of(vendor: str, memory_total_mb: int) -> str:
    """显存分档：none / low / entry / mid / high（阈值含下界）。"""
    if vendor != "nvidia":
        return "none"
    gb = memory_total_mb / 1024.0
    if gb < 6.0:
        return "low"
    if gb < 12.0:
        return "entry"
    if gb < 20.0:
        return "mid"
    return "high"


def _cuda_major_ok(max_cuda_version: str) -> bool:
    """驱动支持的 CUDA 上限 ≥ 12（cuda_runtime 钉 cu12 的硬门槛）。"""
    digits = "".join(ch if ch.isdigit() else " " for ch in max_cuda_version).split()
    return bool(digits) and int(digits[0]) >= 12


def _driver_version_at_least(driver_version: str, major: int) -> bool:
    digits = "".join(ch if ch.isdigit() else " " for ch in driver_version).split()
    return bool(digits) and int(digits[0]) >= major


def profile(snapshot: dict[str, Any], cuda_runtime_installed: bool) -> dict[str, Any]:
    """探测快照 + CUDA 运行库安装态 → 设备档位与各引擎能力结论。"""
    vendor = str(snapshot.get("vendor") or "none")
    name = str(snapshot.get("name") or "")
    memory_total_mb = int(snapshot.get("memory_total_mb") or 0)
    max_cuda_version = str(snapshot.get("max_cuda_version") or "")
    tier = tier_of(vendor, memory_total_mb)
    is_nvidia = vendor == "nvidia" and tier != "none"

    cuda_ok = is_nvidia and _cuda_major_ok(max_cuda_version)
    driver_old = is_nvidia and not _cuda_major_ok(max_cuda_version)
    driver_guidance = {
        "needed": driver_old,
        "url": _DRIVER_URL,
        "min_driver": str(_MIN_DRIVER_MAJOR),
        "reason": f"驱动支持的 CUDA 上限 {max_cuda_version or '未知'} 低于 12，"
        "GPU 加速（CUDA 运行库）无法启用" if driver_old else "",
    }

    vram_gb = memory_total_mb / 1024.0
    caps = {
        # faster-whisper（ctranslate2 CUDA + cuda_runtime DLL，已实装）
        "faster_whisper_gpu": {
            "ok": cuda_ok and vram_gb >= 4.0,
            "ready": cuda_ok and vram_gb >= 4.0 and cuda_runtime_installed,
            "hint": "" if cuda_ok and vram_gb >= 4.0 else "需 4GB+ 显存且驱动支持 CUDA 12+",
        },
        # IndexTTS-2.5 音色克隆（registry notes：4GB+ 显存；tts-venv 按
        # _gpu_variant 装 cu128/CPU 轮——ready 由前端组合 tts 运行时状态）
        "indextts2_gpu": {
            "ok": cuda_ok and vram_gb >= 4.0,
            "ready": False,
            "hint": "配音 TTS 页安装运行环境后生效（N 卡自动装 CUDA 轮）",
        },
        # 人声分离：交付栈是 audio-separator/MDX-Net（onnxruntime CPU，tts-venv）；
        # demucs GPU 路线（CPU 实测 RTF 1.95x / GPU 0.22x）是未接线的能力储备
        "vocal_separation_gpu": {
            "ok": cuda_ok and vram_gb >= 4.0,
            "ready": False,
            "hint": "当前走 CPU（MDX-Net）；GPU 路线待接线",
        },
        # 本地视觉轨三档（llama.cpp llama-server，非 torch 体系——GPU 取决于
        # llama-server 是否 CUDA 构建，属资产层；显存为 fp16 权重估算）
        "local_visual_2b": {
            "ok": is_nvidia and vram_gb >= 6.0,
            "ready": False,
            "hint": "需 llama.cpp CUDA 构建资产（资产库提供后生效）",
        },
        "local_visual_4b": {
            "ok": is_nvidia and vram_gb >= 8.0,
            "ready": False,
            "hint": "需 llama.cpp CUDA 构建资产（资产库提供后生效）",
        },
        "local_visual_8b": {
            "ok": is_nvidia and vram_gb >= 16.0,
            "ready": False,
            "hint": "需 llama.cpp CUDA 构建资产（资产库提供后生效）",
        },
    }
    runtime_tail = "（安装 CUDA 运行库后生效）" if is_nvidia and not cuda_runtime_installed else ""
    recommendation = (
        "推荐启用云端引擎（百炼）：本地 GPU 加速不可用或显存不足"
        if tier in ("none", "low")
        else "本地 GPU 引擎可启用" + runtime_tail
    )
    return {
        "tier": tier,
        "tier_label": _TIER_LABELS[tier],
        "vendor": vendor,
        "gpu_name": name,
        "memory_total_mb": memory_total_mb,
        "max_cuda_version": max_cuda_version,
        "cuda_runtime_installed": cuda_runtime_installed,
        "caps": caps,
        "driver_guidance": driver_guidance,
        "recommendation": recommendation,
    }
