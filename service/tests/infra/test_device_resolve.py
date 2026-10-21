"""设备解析：意图 + 能力表 → 本次设备。cuda 是承诺，auto 才允许落 CPU。

解析结论只是**预期**：回执的 actual 永远来自 worker/引擎证据（规格 §3.6）。
待定态绝不固化成 CPU——服务刚启动几秒内的快照不能替用户决定走 CPU。
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest

from dramaclip.infra import compute, device_profile, device_resolve

_COMPONENTS = (
    "asr.faster_whisper",
    "asr.sensevoice",
    "asr.paraformer",
    "tts.indextts2",
    "tts.cosyvoice",
    "tts.cosyvoice3",
)


@pytest.fixture
def fake_profile(monkeypatch: pytest.MonkeyPatch):
    """把能力表变成测试可写的字典；快照与三处安装态读取一并桩掉。

    gpu.snapshot 必须桩成「已就绪」：真探测在测试进程里是待定态，
    所有 auto/cuda 用例会集体走进 pending 分支而测不到判据。
    """
    state: dict[str, dict[str, dict[str, Any]]] = {"caps": {}}

    def _set(caps: dict[str, dict[str, Any]]) -> None:
        state["caps"] = caps

    def _fake(snapshot: dict[str, Any], installed: bool, **kwargs: Any) -> dict[str, Any]:
        return {"caps": state["caps"], "vendor": snapshot.get("vendor", "none")}

    monkeypatch.setattr(
        device_resolve.gpu, "snapshot", lambda force=False: {"ready": True, "vendor": "nvidia"}
    )
    monkeypatch.setattr(device_profile, "profile", _fake)
    monkeypatch.setattr(device_resolve.cuda_runtime, "status", lambda _d: {"installed": True})
    monkeypatch.setattr(
        device_resolve.tts_runtime, "ort_state", lambda _d: {"variant": "gpu", "gpu": True}
    )
    monkeypatch.setattr(device_resolve.tts_runtime, "torch_variant", lambda _d: "cuda")
    return _set


def _ready(cap_key: str, *, ok: bool = True, reason: str = "") -> dict[str, dict[str, Any]]:
    return {cap_key: {"ok": ok, "ready": True, "hint": "", "reason": reason}}


def _not_ready(cap_key: str, *, ok: bool, reason: str) -> dict[str, dict[str, Any]]:
    return {cap_key: {"ok": ok, "ready": False, "hint": f"整句说明：{reason}", "reason": reason}}


@pytest.mark.parametrize("component", _COMPONENTS)
def test_every_mapped_component_names_a_real_cap(component: str, fake_profile) -> None:
    cap = device_resolve.resolve(component, "auto", Path("data")).cap
    assert cap in device_profile.CAPS


def test_auto_with_ready_cap_resolves_cuda(fake_profile) -> None:
    fake_profile(_ready("indextts2_gpu"))
    out = device_resolve.resolve("tts.indextts2", "auto", Path("data"))
    assert (out.resolved, out.actual, out.device) == ("cuda", "cuda", "cuda")
    assert out.reason == "" and out.downgraded is False


def test_auto_with_unready_cap_goes_cpu_with_reason(fake_profile) -> None:
    fake_profile(_not_ready("indextts2_gpu", ok=True, reason="本地运行环境的 torch 是 CPU 轮"))
    out = device_resolve.resolve("tts.indextts2", "auto", Path("data"))
    assert (out.resolved, out.actual, out.device) == ("cpu", "cpu", "cpu")
    assert out.reason == "本地运行环境的 torch 是 CPU 轮"
    # ok=True 而 ready=False：硬件过关、运行时没装好——这才叫「本次被降级」
    assert out.downgraded is True


def test_auto_with_hardware_exclusion_is_not_a_downgrade(fake_profile) -> None:
    fake_profile(
        _not_ready(
            "indextts2_gpu", ok=False, reason="算力 sm_6.1 低于 torch cu128 下界 sm_70"
        )
    )
    out = device_resolve.resolve("tts.indextts2", "auto", Path("data"))
    assert out.device == "cpu"
    assert out.downgraded is False, "永久下限不写成「降级」，否则每次日志都在喊降级"


def test_explicit_cpu_is_never_upgraded(fake_profile) -> None:
    fake_profile(_ready("faster_whisper_gpu"))
    out = device_resolve.resolve("asr.faster_whisper", "cpu", Path("data"))
    assert (out.resolved, out.actual, out.device) == ("cpu", "cpu", "cpu")
    assert out.requested == "cpu"


def test_explicit_cuda_raises_before_the_engine_is_built(fake_profile) -> None:
    fake_profile(
        _not_ready(
            "indextts2_gpu", ok=False, reason="算力 sm_6.1 低于 torch cu128 下界 sm_70"
        )
    )
    with pytest.raises(compute.ComputeUnavailableError) as info:
        device_resolve.resolve("tts.indextts2", "cuda", Path("data"))
    assert "tts.indextts2" in str(info.value)
    assert "算力 sm_6.1 低于 torch cu128 下界 sm_70" in str(info.value)


def test_pending_snapshot_is_handed_to_the_engine_not_forced_to_cpu(
    fake_profile, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_profile({})
    monkeypatch.setattr(
        device_resolve.gpu,
        "snapshot",
        lambda force=False: {"ready": False, "vendor": "unknown"},
    )
    out = device_resolve.resolve("asr.faster_whisper", "cuda", Path("data"))
    assert out.device == "auto", "探测未完成时 cuda 承诺不能凭空兑现，也不能判 CPU"
    assert out.resolved == "unknown" and out.actual == "unknown"
    assert "探测中" in out.reason
    assert out.downgraded is False


def test_resolution_does_not_sign_the_receipt(fake_profile) -> None:
    """解析给的是**预期**设备，不是运行证据：结构里不许有 fallback，也不带耗时/产物字段。"""
    fake_profile(_ready("funasr_gpu"))
    out = device_resolve.resolve("asr.sensevoice", "auto", Path("data"))
    assert out.component == "asr.sensevoice" and out.cap == "funasr_gpu"
    assert out.reason == ""
    assert not hasattr(out, "fallback"), "回退是运行期事实，解析层无权代签"
    assert {f.name for f in fields(out)} == {
        "component", "cap", "requested", "resolved", "actual", "device", "reason", "downgraded",
    }, "字段膨胀等于开始替回执记账"


def test_unknown_component_is_refused(fake_profile) -> None:
    fake_profile(_ready("funasr_gpu"))
    with pytest.raises(KeyError):
        device_resolve.resolve("asr.whisper_large", "auto", Path("data"))


def test_separation_and_encode_are_not_resolvable(fake_profile) -> None:
    """§3.5/§3.6：分离恒 auto 交给 worker，编码有自己的试编解析器——这里都不许登记。"""
    fake_profile(_ready("vocal_separation_gpu"))
    for component in ("tts.separation", "video.encode", "tts.reference_clean.filter"):
        with pytest.raises(KeyError):
            device_resolve.resolve(component, "auto", Path("data"))


def test_resolve_engine_passes_through_engines_without_a_cap(fake_profile) -> None:
    fake_profile(_ready("indextts2_gpu"))
    assert device_resolve.resolve_engine("tts", "edge", "cuda", Path("data")) is None
    assert device_resolve.resolve_engine("tts", "kokoro", "cuda", Path("data")) is None
    assert device_resolve.resolve_engine("asr", "dashscope_cloud", "cuda", Path("data")) is None
    hit = device_resolve.resolve_engine("tts", "cosyvoice", "auto", Path("data"))
    assert hit is not None and hit.component == "tts.cosyvoice"


def test_unknown_requested_value_is_a_param_error(fake_profile) -> None:
    fake_profile(_ready("funasr_gpu"))
    with pytest.raises(ValueError):
        device_resolve.resolve("asr.sensevoice", "directml", Path("data"))
