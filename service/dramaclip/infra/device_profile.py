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


def _torch_variant_is_cuda() -> bool:
    """tts-venv 变体标记 == cuda（打包态 funasr worker 环境的零探针判据）。"""
    from dramaclip.infra.model_manager import tts_runtime
    from dramaclip.infra.paths import resolve_data_dir

    return tts_runtime.torch_variant(resolve_data_dir()) == "cuda"


# dev 态服务进程自带 torch（service/.venv GPU 轮）——funasr 在主进程内跑，
# ready 判据必须看它的**执行级实况**：is_available 只是设备级检测，sm_52 这类
# 无内核的卡它照样 True，第一次真算就崩（真机 2026-10-20 实锤：M4000 cu126
# is_available=True 但 kernel 全不可执行——「已在 GPU」一度是假话）。
# 进程内缓存：torch 导入秒级，只付一次。
_SERVICE_TORCH_STATE: tuple[bool, bool, str] | None = None


def _service_torch_state() -> tuple[bool, bool, str]:
    """（torch_cuda 可真算, torch 在场, 算力标签）。探针一次定案，进程内缓存。"""
    global _SERVICE_TORCH_STATE
    if _SERVICE_TORCH_STATE is None:
        try:
            import torch

            if not torch.cuda.is_available():
                _SERVICE_TORCH_STATE = (False, True, "")
            else:
                cc = ".".join(map(str, torch.cuda.get_device_capability(0)))
                try:
                    x = torch.randn(8, 8, device="cuda")
                    _ = bool((x @ x.T).sum())
                    _SERVICE_TORCH_STATE = (True, True, cc)
                except Exception:  # noqa: BLE001 - 无内核卡：检测过、执行必崩
                    _SERVICE_TORCH_STATE = (False, True, cc)
        except Exception:  # noqa: BLE001 - 打包态主进程零 torch：判据回落 tts-venv 标记
            _SERVICE_TORCH_STATE = (False, False, "")
    return _SERVICE_TORCH_STATE


def _service_torch_is_cuda() -> bool:
    return _service_torch_state()[0]


# ctranslate2 的 GPU 内核下界：低于此算力（如 Maxwell sm_52）没有可执行 kernel，
# whisper GPU 加速永久不可用——上游硬边界，与驱动/运行库无关（10 月中定论）。
_CTRANSLATE2_MIN_CC = (6, 1)


def _parse_cc(raw: str) -> tuple[int, int] | None:
    try:
        major, minor = raw.split(".")
        return (int(major), int(minor))
    except (ValueError, AttributeError):
        return None


def profile(
    snapshot: dict[str, Any],
    cuda_runtime_installed: bool,
    *,
    separation_ort: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """探测快照 + CUDA 运行库/ORT 安装态 → 设备档位与各引擎能力结论。

    ``separation_ort`` 是 tts_runtime.ort_state：安装期真实 CUDA session 探测的
    marker。安装态与可用态分开——GPU 轮装上了但 session 落 CPU 时必须如实不 ready。
    """
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
    separation_ready = bool(
        cuda_ok and vram_gb >= 4.0 and cuda_runtime_installed
        and separation_ort is not None and separation_ort.get("gpu")
    )
    if not (cuda_ok and vram_gb >= 4.0):
        separation_hint = "需 4GB+ 显存且驱动支持 CUDA 12+"
    elif not cuda_runtime_installed:
        separation_hint = "CUDA 运行库未安装（安装后可重跑本地运行环境以启用 GPU 分离）"
    elif separation_ort is None or separation_ort.get("variant") in (None, "unknown"):
        separation_hint = "ONNX Runtime 运行后端未探测：重跑本地运行环境以启用 GPU 分离"
    elif not separation_ready:
        separation_hint = str(
            separation_ort.get("reason") or "ONNX Runtime 为 CPU 版，分离走 CPU"
        )
    else:
        separation_hint = ""
    # ctranslate2 对这张卡是否可用：快照里的 compute_cap（nvidia-smi 采）与内核下界比；
    # 快照缺该字段时回落 torch 执行级探针的算力标签
    cc_raw = str(snapshot.get("compute_cap") or "") or _service_torch_state()[2]
    cc = _parse_cc(cc_raw)
    whisper_blocked = cc is not None and cc < _CTRANSLATE2_MIN_CC
    torch_usable, _torch_present, _ = _service_torch_state()
    caps = {
        # faster-whisper（ctranslate2 CUDA + cuda_runtime DLL，已实装）。
        # 算力低于 ctranslate2 内核下界（如 Maxwell sm_52）时如实标「不支持」，
        # 不给一颗运行库装上也点不亮的绿灯
        "faster_whisper_gpu": {
            "ok": cuda_ok and vram_gb >= 4.0 and not whisper_blocked,
            "ready": (
                cuda_ok and vram_gb >= 4.0 and not whisper_blocked and cuda_runtime_installed
            ),
            "hint": (
                f"此卡算力 sm_{cc_raw} 无 ctranslate2 计算内核，whisper GPU 加速不可用；"
                "转写请用 funasr（N 卡上已在 GPU）或 CPU"
                if whisper_blocked
                else "" if cuda_ok and vram_gb >= 4.0 else "需 4GB+ 显存且驱动支持 CUDA 12+"
            ),
        },
        # IndexTTS-2.5 音色克隆（registry notes：4GB+ 显存；tts-venv 按
        # _gpu_variant 装 cu128/CPU 轮——ready 由前端组合 tts 运行时状态）
        "indextts2_gpu": {
            "ok": cuda_ok and vram_gb >= 4.0,
            "ready": False,
            "hint": "安装后由运行时回执确认实际设备（安装态不等于已启用 GPU）",
        },
        # funasr 本地 ASR：打包态与双栈 TTS 共用 tts-venv（变体标记判据）；
        # dev 态 funasr 在主进程内跑（service/.venv GPU 轮），torch 实况优先于标记
        "funasr_gpu": {
            "ok": cuda_ok and vram_gb >= 4.0,
            "ready": (
                cuda_ok
                and vram_gb >= 4.0
                and (_service_torch_is_cuda() or _torch_variant_is_cuda())
            ),
            "hint": "ASR 页安装运行环境后生效（N 卡自动装 CUDA 轮）",
        },
        # 人声分离：audio-separator/MDX-Net 走 onnxruntime，GPU 需要 CUDA EP +
        # cuda_runtime 的 cublas/cudnn/cudart/cufft。ready 以安装期真实 session
        # 探测的 marker 为准；实际任务仍由 worker 回执二次确认。
        "vocal_separation_gpu": {
            "ok": cuda_ok and vram_gb >= 4.0,
            "ready": separation_ready,
            "hint": separation_hint,
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
