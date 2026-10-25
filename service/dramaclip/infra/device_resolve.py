"""唯一设备解析入口：用户意图 + 能力表 → 本次设备（预期，不是运行证据）。

能力表（``device_profile.profile(...)["caps"]``）判「这台机器现在能不能上 CUDA」，
本模块只按 ``ok``/``ready``/``reason`` 取数，**不解析 hint 文案**；引擎侧不再各自读
设置（旧状：runtime/factory/pool/preview/selftest 五处各读一次 ``asr.device``/``tts.device``）。

不纳入解析的两类，各有自己的解析器并遵守同一契约「解析 → 运行证据 → ComputeReport」：
- 人声分离：没有设备开关，恒 ``auto`` 交给 worker（worker 的 provider 探测会把
  「缺 CUDA EP / CUDA 试跑失败」的真实原因写进回执；在入口预判 CPU 反而丢掉原因）。
- 视频编码：``encoder.pick_hw_encoder`` 用真实试编决定，下限不可预知，只能试。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dramaclip.infra import compute, device_profile, gpu
from dramaclip.infra.model_manager import cuda_runtime, tts_runtime

#: 引擎 → component。云端引擎与 kokoro 不在此表：kokoro 没有对应的能力判据，
#: 猜一个 cap 等于替它宣布可用性，原样透传设备串才是诚实的。
ASR_ENGINES: dict[str, str] = {
    "faster_whisper": "asr.faster_whisper",
    "sensevoice": "asr.sensevoice",
    "paraformer": "asr.paraformer",
}
TTS_ENGINES: dict[str, str] = {
    "indextts2": "tts.indextts2",
    "cosyvoice": "tts.cosyvoice",
    "cosyvoice3": "tts.cosyvoice3",
}
#: component → cap。torch cu128 那套运行时同时承担 indextts2 / cosyvoice 系，
#: 共用 ``indextts2_gpu`` 这一个 cap（键名是历史名，实质是「torch 栈 GPU」）。
_COMPONENT_CAPS: dict[str, str] = {
    "asr.faster_whisper": "faster_whisper_gpu",
    "asr.sensevoice": "funasr_gpu",
    "asr.paraformer": "funasr_gpu",
    "tts.indextts2": "indextts2_gpu",
    "tts.cosyvoice": "indextts2_gpu",
    "tts.cosyvoice3": "indextts2_gpu",
}

_PENDING_REASON = "显卡状态探测中，交给引擎自判"


@dataclass(frozen=True)
class DeviceResolution:
    component: str
    cap: str
    requested: str
    resolved: str
    actual: str
    device: str
    reason: str
    downgraded: bool = False


def resolve(component: str, requested: str | None, data_dir: Path) -> DeviceResolution:
    """把 ``requested``（auto/cuda/cpu/None）解析成引擎该收的设备串。

    ``cuda`` 是承诺：cap 不 ready 时立刻抛 ``ComputeUnavailableError``，在拉起模型
    或 worker **之前**失败。``cpu`` 恒 CPU。``auto`` 按 ready 选路，硬件过关但运行时
    未就绪时 ``downgraded=True``。快照待定 → ``device="auto"``，交给引擎自判。
    """
    cap = _COMPONENT_CAPS[component]  # 未登记的组件没有判据：KeyError 比猜一个强
    intent = compute.normalize_requested(requested)
    snapshot = gpu.snapshot()
    if not snapshot.get("ready"):
        return DeviceResolution(
            component=component,
            cap=cap,
            requested=intent,
            resolved="unknown",
            actual="unknown",
            device="auto",
            reason=_PENDING_REASON,
        )
    prof = device_profile.profile(
        snapshot,
        cuda_runtime.status(data_dir)["installed"],
        separation_ort=tts_runtime.ort_state(data_dir),
        torch_variant=tts_runtime.torch_variant(data_dir),
    )
    entry: dict[str, Any] = prof["caps"].get(cap) or {"ok": False, "ready": False, "reason": ""}
    ok = bool(entry["ok"])
    ready = bool(entry["ready"])
    reason = str(entry["reason"] or entry.get("hint") or "")
    if intent == "cuda":
        if not ready:
            raise compute.ComputeUnavailableError(
                f"{component} 请求 cuda，本机能力表判不可用：{reason or '原因未给出'}"
            )
        return DeviceResolution(component, cap, "cuda", "cuda", "cuda", "cuda", "")
    if intent == "cpu":
        return DeviceResolution(component, cap, "cpu", "cpu", "cpu", "cpu", "")
    if ready:
        # torch_device 由 profile 按主机厂商给出（nvidia=cuda / intel+xpu 轮=xpu / 其余 cpu）
        device = str(prof.get("torch_device") or "cuda")
        return DeviceResolution(component, cap, "auto", device, device, device, "")
    return DeviceResolution(
        component, cap, "auto", "cpu", "cpu", "cpu", reason, downgraded=ok
    )


def resolve_engine(
    kind: str, engine: str, requested: str | None, data_dir: Path
) -> DeviceResolution | None:
    """按引擎名解析；``None`` = 该引擎没有能力判据（云端/kokoro），调用方原样透传。"""
    table = ASR_ENGINES if kind == "asr" else TTS_ENGINES
    component = table.get(engine)
    if component is None:
        return None
    return resolve(component, requested, data_dir)
