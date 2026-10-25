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
    "none": "未检测到独立显卡",
    "low": "入门（<6GB 显存）",
    "entry": "标准（6-11GB 显存）",
    "mid": "主力（12-19GB 显存）",
    "high": "高配（20GB+ 显存）",
}
# 非 NVIDIA 主机有卡是事实：标签说清「硬编可用、AI 走 CPU」，别再冒充「没有显卡」。
_VENDOR_TIER_LABELS = {
    "amd": "AMD 显卡 · 视频硬编，AI 引擎走 CPU",
    "intel": "Intel 显卡 · 视频硬编，AI 引擎走 CPU",
    "other": "其他显卡 · AI 引擎走 CPU",
}
_VENDOR_RECOMMENDATIONS = {
    "amd": "视频导出可用本卡硬件编码（AMF，导出时真试编）；"
    "ASR/TTS 加速需 NVIDIA CUDA，当前走 CPU，可改用云端引擎",
    "intel": "视频导出可用本卡硬件编码（QSV，导出时真试编）；"
    "ASR/TTS 加速需 NVIDIA CUDA，当前走 CPU，可改用云端引擎",
    "other": "视频导出会在真试编后选择硬编或 libx264；ASR/TTS 加速需 NVIDIA CUDA，当前走 CPU",
}
_PENDING_LABEL = "显卡探测中…"
_PENDING_RECOMMENDATION = "显卡状态探测中：本地引擎均可先用 CPU 运行"
_NO_CARD_RECOMMENDATION = "推荐启用云端引擎（百炼）：本地 GPU 加速不可用或显存不足"
_VRAM_UNKNOWN_LABEL = "NVIDIA 显卡 · 显存信息不可读"

#: 能力键的唯一清单：设备解析入口与前端都按这张表取数，别处不再抄一份。
CAPS = (
    "faster_whisper_gpu",
    "funasr_gpu",
    "indextts2_gpu",
    "vocal_separation_gpu",
    "local_visual_2b",
    "local_visual_4b",
    "local_visual_8b",
)
_PROBING_HINTS = {
    "faster_whisper_gpu": "显卡状态探测中：转写暂走 CPU",
    "funasr_gpu": "显卡状态探测中：转写暂走 CPU",
    "indextts2_gpu": "显卡状态探测中：音色克隆暂走 CPU",
    "vocal_separation_gpu": "显卡状态探测中：人声分离暂走 CPU",
    "local_visual": "显卡状态探测中",
}
_NON_NVIDIA_HINTS = {
    "faster_whisper_gpu": "转写 GPU 加速需要 NVIDIA CUDA，当前走 CPU",
    "funasr_gpu": "转写 GPU 加速需要 NVIDIA CUDA，当前走 CPU",
    "indextts2_gpu": "音色克隆 GPU 加速需要 NVIDIA CUDA，当前走 CPU",
    "vocal_separation_gpu": "人声分离 GPU 加速仅支持 NVIDIA CUDA，当前走 CPU",
    "local_visual": "本地视觉模型需要 NVIDIA CUDA，当前不可用",
}
_REASON_PROBING = "显卡状态探测中"
_REASON_NON_NVIDIA = "本机无 NVIDIA 显卡，加速需要 CUDA"
_REASON_DRIVER_UNKNOWN = "未能读取 NVIDIA 驱动信息"
_REASON_DRIVER_OLD = "驱动支持的 CUDA 上限低于 12"
_REASON_VRAM_UNKNOWN = "显存信息不可读"
_REASON_VRAM_LOW = "显存不足 4GB"
_REASON_RUNTIME_MISSING = "CUDA 运行库未安装"
_REASON_TORCH_CPU_WHEEL = "本地运行环境的 torch 是 CPU 轮"
# torch cu128（tts-venv）的可执行内核下界：低于此算力装得上、算子无内核（2026-10-16 实测）
_TORCH_MIN_CC = (7, 0)


def tier_of(vendor: str, memory_total_mb: int) -> str:
    """显存分档：只有 NVIDIA 且显存真读得到才分档，其余一律 none。

    「显存读不到」不是小卡：非 N 卡不采信 AdapterRAM（UInt32 普遍失真），N 卡掉了
    nvidia-smi 也是 0——都归 none，由厂商标签与驱动分支各自说清原因。
    """
    if vendor != "nvidia" or memory_total_mb <= 0:
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


def _cap(ok: bool, ready: bool, hint: str, reason: str) -> dict[str, Any]:
    """能力项的形状唯一出口：reason 是给程序与界面标签用的短句，hint 是给人看的整句。"""
    return {"ok": ok, "ready": ready, "hint": hint, "reason": reason}


def _tts_torch_variant(override: str | None) -> str:
    """tts-venv 的 torch 变体：调用方给了就用调用方的（按它自己的 data_dir），否则现读全局。"""
    if override is not None:
        return override if override in ("cuda", "cpu", "xpu") else "unknown"
    from dramaclip.infra.model_manager import tts_runtime as _ttr
    from dramaclip.infra.paths import resolve_data_dir as _rdd

    value = _ttr.torch_variant(_rdd())
    return value if value in ("cuda", "cpu", "xpu") else "unknown"


def _snapshot_intel_xpu_adapter(snapshot: dict[str, Any]) -> bool:
    """快照里是否存在 Arc/Ultra 级 Intel 适配器（XPU 轮的可运行判据）。

    名称 token 判代：Arc 独显与 Meteor Lake+ 核显的适配器名都带 arc/ultra；
    老 Gen9.5 核显（如 UHD 630）无 XPU 后端，名称不含两者 → 不判真。
    """
    adapters = snapshot.get("adapters") or []
    for adapter in adapters:
        if not isinstance(adapter, dict):
            continue
        vendor_ok = (
            str(adapter.get("vendor_id") or "") == "0x8086"
            or str(adapter.get("vendor") or "") == "intel"
        )
        if not vendor_ok:
            continue
        name_l = str(adapter.get("name") or "").lower()
        if "arc" in name_l or "ultra" in name_l:
            return True
    return False


def profile(
    snapshot: dict[str, Any],
    cuda_runtime_installed: bool,
    *,
    separation_ort: dict[str, Any] | None = None,
    torch_variant: str | None = None,
) -> dict[str, Any]:
    """探测快照 + 运行库/ORT/torch 安装态 → 设备档位与各引擎能力结论。

    ``separation_ort`` 是 tts_runtime.ort_state（安装期真实 session 探测的 marker）；
    ``torch_variant`` 是 tts_runtime.torch_variant。两者由调用方按**自己的 data_dir**
    读进来：本函数不许再去猜全局 data_dir，否则 system.health 与解析入口会各得结论。
    安装态与可用态分开——GPU 轮装上了但 session 落 CPU 时必须如实不 ready。
    """
    vendor = str(snapshot.get("vendor") or "none")
    name = str(snapshot.get("name") or "")
    memory_total_mb = int(snapshot.get("memory_total_mb") or 0)
    max_cuda_version = str(snapshot.get("max_cuda_version") or "")
    probing = vendor == "unknown"
    nvidia_hw = vendor == "nvidia"
    tier = tier_of(vendor, memory_total_mb)
    is_nvidia = nvidia_hw and tier != "none"  # N 卡且显存可读
    vram_gb = memory_total_mb / 1024.0

    # ctranslate2 对这张卡是否可用：快照里的 compute_cap（nvidia-smi 采）与内核下界比；
    # 快照缺该字段时回落 torch 执行级探针的算力标签
    cc_raw = str(snapshot.get("compute_cap") or "") or _service_torch_state()[2]
    cc = _parse_cc(cc_raw)
    whisper_blocked = cc is not None and cc < _CTRANSLATE2_MIN_CC
    torch_blocked = cc is not None and cc < _TORCH_MIN_CC

    # §3.3 三分支：读不到（unknown）与读到了但太低（old）是两件事，前者不能冒充后者。
    driver_old = nvidia_hw and max_cuda_version != "" and not _cuda_major_ok(max_cuda_version)
    driver_unknown = nvidia_hw and max_cuda_version == ""
    guidance_reason = ""
    if driver_unknown:
        guidance_reason = (
            "未能读取 NVIDIA 驱动的 CUDA 上限（nvidia-smi 不可用或查询失败），"
            "无法确认 CUDA 12 支持：请重装 NVIDIA 驱动后重试"
        )
    elif driver_old:
        guidance_reason = (
            f"驱动支持的 CUDA 上限 {max_cuda_version} 低于 12，GPU 加速（CUDA 运行库）无法启用"
        )
    driver_guidance = {
        "needed": driver_unknown or driver_old,
        "url": _DRIVER_URL,
        "min_driver": str(_MIN_DRIVER_MAJOR),
        "reason": guidance_reason,
    }

    cuda_ok = is_nvidia and _cuda_major_ok(max_cuda_version)
    variant = _tts_torch_variant(torch_variant)
    # Intel XPU 双门：主机有 Arc/Ultra 级适配器 且 tts-venv 装的是 xpu 轮——
    # 两条都真才点亮 torch 系引擎（funasr/indextts/cosyvoice/kokoro）的 XPU 结论
    intel_xpu = (
        vendor == "intel"
        and variant == "xpu"
        and _snapshot_intel_xpu_adapter(snapshot)
    )

    if probing:
        tier_label = _PENDING_LABEL
    elif nvidia_hw:
        tier_label = _TIER_LABELS[tier] if tier != "none" else _VRAM_UNKNOWN_LABEL
    elif intel_xpu:
        tier_label = "Intel 显卡 · XPU 加速（算子覆盖未经验证）"
    else:
        tier_label = _VENDOR_TIER_LABELS.get(vendor) or _TIER_LABELS["none"]

    runtime_tail = "（安装 CUDA 运行库后生效）" if is_nvidia and not cuda_runtime_installed else ""
    # 优先级 §3.3：驱动不可读 > 显存不可读 > 驱动过旧 > 常规分档
    if probing:
        recommendation = _PENDING_RECOMMENDATION
    elif driver_unknown:
        recommendation = (
            "NVIDIA 驱动信息不可读（nvidia-smi 不可用或查询失败）：修复驱动后重试，或改用云端引擎"
        )
    elif nvidia_hw and not is_nvidia:
        recommendation = (
            "NVIDIA 显卡在场但显存信息不可读：重装 NVIDIA 驱动后重试，或改用云端引擎"
        )
    elif driver_old:
        recommendation = (
            f"驱动支持的 CUDA 上限 {max_cuda_version} 低于 12：先更新 NVIDIA 驱动，或改用云端引擎"
        )
    elif vendor in _VENDOR_RECOMMENDATIONS:
        recommendation = _VENDOR_RECOMMENDATIONS[vendor]
    elif tier in ("none", "low"):
        recommendation = _NO_CARD_RECOMMENDATION
    else:
        recommendation = "本地 GPU 引擎可启用" + runtime_tail
    if intel_xpu and not probing:
        recommendation = (
            "ASR/音色克隆可走 Intel XPU（算子覆盖未经验证，失败自动回退 CPU 或改用云端引擎）；"
            "视频导出可用本卡硬件编码（QSV，导出时真试编）"
        )

    def note(cap_key: str, local: bool = False) -> tuple[str, str, bool]:
        """待定/非 NVIDIA 两类短路：(hint, reason, 是否短路)。"""
        short = cap_key if not local else "local_visual"
        if probing:
            return _PROBING_HINTS[short], _REASON_PROBING, True
        if not nvidia_hw:
            return _NON_NVIDIA_HINTS[short], _REASON_NON_NVIDIA, True
        return "", "", False

    def hardware_block() -> tuple[str, str]:
        """NVIDIA 主机的硬件门禁：显存/驱动过关则空，否则给 (hint, reason)。"""
        if driver_unknown:
            return "未能读取 NVIDIA 驱动信息，无法确认 CUDA 12 支持", _REASON_DRIVER_UNKNOWN
        if not is_nvidia:
            return "需 4GB+ 显存且驱动支持 CUDA 12+（显存信息不可读）", _REASON_VRAM_UNKNOWN
        if vram_gb < 4.0:
            return "需 4GB+ 显存且驱动支持 CUDA 12+（显存不足 4GB）", _REASON_VRAM_LOW
        if not cuda_ok:
            return "需 4GB+ 显存且驱动支持 CUDA 12+", _REASON_DRIVER_OLD
        return "", ""

    hw_hint, hw_reason = hardware_block()
    hardware_ok = hw_hint == ""

    # 分支顺序即 §3.4 的口径：待定/非 NVIDIA 的厂商文案 → NVIDIA 硬件门禁（含驱动不可读）
    # → 该条栈自己的运行时/算力判据。写反了就会给 AMD 主机报「CUDA 运行库未安装」。
    fw_hint, fw_reason, fw_short = note("faster_whisper_gpu")
    # faster-whisper（ctranslate2 CUDA + cuda_runtime DLL，已实装）：算力低于内核下界
    # （如 Maxwell sm_52）时如实标「不支持」，不给一颗运行库装上也点不亮的绿灯
    whisper_ok = hardware_ok and not whisper_blocked
    whisper_ready = whisper_ok and cuda_runtime_installed
    if not fw_short:
        if not hardware_ok:
            fw_hint, fw_reason = hw_hint, hw_reason
        elif whisper_blocked:
            fw_hint = (
                f"此卡算力 sm_{cc_raw} 无 ctranslate2 计算内核，whisper GPU 加速不可用；"
                "转写请用 funasr（N 卡上已在 GPU）或 CPU"
            )
            fw_reason = f"算力 sm_{cc_raw} 低于 ctranslate2 下界 sm_61"
        elif not cuda_runtime_installed:
            fw_hint, fw_reason = "CUDA 运行库未安装（安装后转写可走 GPU）", _REASON_RUNTIME_MISSING
        else:
            fw_hint, fw_reason = "", ""

    tts_hint, tts_reason, tts_short = note("indextts2_gpu")
    # IndexTTS-2.5 音色克隆（registry notes：4GB+ 显存）走 tts-venv 的 torch cu128：
    # ready 由该变体决定——「装上了」不等于「在 GPU 上算」
    indextts_ok = hardware_ok and not torch_blocked
    indextts_ready = indextts_ok and variant == "cuda"
    if not tts_short:
        if not hardware_ok:
            tts_hint, tts_reason = hw_hint, hw_reason
        elif torch_blocked:
            tts_hint = f"此卡算力 sm_{cc_raw} 低于 torch cu128 下界 sm_70，音色克隆走 CPU"
            tts_reason = f"算力 sm_{cc_raw} 低于 torch cu128 下界 sm_70"
        elif variant != "cuda":
            tts_hint = "本地运行环境的 torch 是 CPU 轮：重跑「安装运行环境」可启用 GPU 克隆"
            tts_reason = _REASON_TORCH_CPU_WHEEL
        else:
            tts_hint, tts_reason = "", ""

    fa_hint, fa_reason, fa_short = note("funasr_gpu")
    # funasr 不写静态下限：它可能跑在打包态的 tts-venv（cu128）或 dev 态主进程 torch
    # （构建不同，sm_52 也能实跑在 GPU）——两种实况分别探测，静态线会造假阴性。
    funasr_ok = hardware_ok
    funasr_ready = funasr_ok and (_service_torch_is_cuda() or variant == "cuda")
    if not fa_short:
        if not hardware_ok:
            fa_hint, fa_reason = hw_hint, hw_reason
        elif not funasr_ready:
            fa_hint = "ASR 页安装运行环境后生效（N 卡自动装 CUDA 轮）"
            fa_reason = _REASON_TORCH_CPU_WHEEL
        else:
            fa_hint, fa_reason = "", ""

    # 人声分离走 audio-separator/onnxruntime：GPU 需要 CUDA EP + cuda_runtime 的
    # cublas/cudnn/cudart/cufft。ready 以安装期真实 session 探测的 marker 为准；
    # 实际任务仍由 worker 回执二次确认。
    sep_hint, sep_reason, sep_short = note("vocal_separation_gpu")
    ort_gpu = bool(separation_ort is not None and separation_ort.get("gpu"))
    separation_ready = hardware_ok and cuda_runtime_installed and ort_gpu
    if not sep_short:
        if not hardware_ok:
            sep_hint, sep_reason = hw_hint, hw_reason
        elif not cuda_runtime_installed:
            sep_hint = "CUDA 运行库未安装（安装后可重跑本地运行环境以启用 GPU 分离）"
            sep_reason = _REASON_RUNTIME_MISSING
        elif separation_ort is None or separation_ort.get("variant") in (None, "unknown"):
            sep_hint = "ONNX Runtime 运行后端未探测：重跑本地运行环境以启用 GPU 分离"
            sep_reason = "ONNX Runtime 后端未探测"
        elif not ort_gpu:
            sep_hint = str(
                (separation_ort or {}).get("reason") or "ONNX Runtime 为 CPU 版，分离走 CPU"
            )
            sep_reason = "ONNX Runtime 为 CPU 后端"
        else:
            sep_hint, sep_reason = "", ""

    # 本地视觉轨三档（llama.cpp llama-server，非 torch 体系——GPU 取决于
    # llama-server 是否 CUDA 构建，属资产层；显存为 fp16 权重估算）
    visual: dict[str, dict[str, Any]] = {}
    for v_key, floor_gb in (
        ("local_visual_2b", 6.0),
        ("local_visual_4b", 8.0),
        ("local_visual_8b", 16.0),
    ):
        v_hint, v_reason, v_short = note(v_key, local=True)
        v_ok = is_nvidia and vram_gb >= floor_gb
        if not v_short:
            if not is_nvidia:
                v_hint, v_reason = hw_hint, hw_reason
            elif not v_ok:
                v_hint = f"本地视觉模型需 {floor_gb:.0f}GB+ 显存（当前 {vram_gb:.1f}GB）"
                v_reason = f"显存不足 {floor_gb:.0f}GB"
            else:
                v_hint = "需 llama.cpp CUDA 构建资产（资产库提供后生效）"
                v_reason = "视觉模型 CUDA 构建资产未入库"
        visual[v_key] = _cap(v_ok, False, v_hint, v_reason)

    caps = {
        "faster_whisper_gpu": _cap(whisper_ok, whisper_ready, fw_hint, fw_reason),
        "indextts2_gpu": _cap(indextts_ok, indextts_ready, tts_hint, tts_reason),
        "funasr_gpu": _cap(funasr_ok, funasr_ready, fa_hint, fa_reason),
        # 分离的 ok 就是硬件门禁：它没有静态算力下界（ORT 在 sm_52 实测可用，官方下限未核对）
        "vocal_separation_gpu": _cap(hardware_ok, separation_ready, sep_hint, sep_reason),
        **visual,
    }
    if intel_xpu:
        # 覆盖 note() 的非 NVIDIA 短路：Intel XPU 主机上 torch 系两引擎点亮 XPU；
        # faster_whisper（ctranslate2 无 XPU 后端）与分离（ORT DML 另批）维持现状。
        caps["funasr_gpu"] = _cap(
            True,
            True,
            "Intel XPU 后端可用（算子覆盖未经验证，首次真算以实况为准）",
            "Intel XPU",
        )
        caps["indextts2_gpu"] = _cap(
            True, True, "Intel XPU 后端（算子覆盖未经验证）", "Intel XPU",
        )
    return {
        "tier": tier,
        "tier_label": tier_label,
        "vendor": vendor,
        "gpu_name": name,
        "memory_total_mb": memory_total_mb,
        "max_cuda_version": max_cuda_version,
        "cuda_runtime_installed": cuda_runtime_installed,
        "torch_device": "xpu" if intel_xpu else ("cuda" if is_nvidia else "cpu"),
        "caps": caps,
        "driver_guidance": driver_guidance,
        "recommendation": recommendation,
    }
