"""能力表的多厂商口径：有卡就说有卡，AI 加速只认 CUDA，读不到不等于太旧。

三条判据各自独立（规格 §3.2/§3.3/§3.5）：厂商标签、驱动可读性、每条栈的算力下界。
开发机（sm_52 + RX 5500 XT）只作回归，任何用例都不许把它的实况当判据。
"""

from __future__ import annotations

from typing import Any

import pytest

from dramaclip.infra import device_profile

_AMD = {
    "ready": True,
    "vendor": "amd",
    "name": "AMD Radeon RX 6600",
    "driver_version": "31.0.12027.9001",
    "max_cuda_version": "",
    "memory_total_mb": 0,
    "compute_cap": "",
    "adapters": [
        {"name": "AMD Radeon RX 6600", "vendor": "amd", "driver_version": "31.0.12027.9001"}
    ],
}
_INTEL = {**_AMD, "vendor": "intel", "name": "Intel(R) UHD Graphics 770"}
_OTHER = {**_AMD, "vendor": "other", "name": "USB 3D Controller"}
_NONE = {**_AMD, "vendor": "none", "name": "", "driver_version": "", "adapters": []}
_PENDING = {**_AMD, "ready": False, "vendor": "unknown", "name": "", "adapters": []}
# NVIDIA 主流独显（RTX 3060 档）：算力 ≥7.0、驱动支持 CUDA 12
_NVIDIA_OK = {
    "ready": True,
    "vendor": "nvidia",
    "name": "NVIDIA GeForce RTX 3060",
    "driver_version": "551.61",
    "max_cuda_version": "12.4",
    "memory_total_mb": 12288,
    "compute_cap": "8.6",
    "adapters": [
        {"name": "NVIDIA GeForce RTX 3060", "vendor": "nvidia", "driver_version": "551.61"}
    ],
}
# GTX 10 存量段（Pascal sm_61）：ctranslate2 能用、torch cu128 不能用、ORT 能用
_GTX10 = {**_NVIDIA_OK, "name": "NVIDIA GeForce GTX 1060", "memory_total_mb": 6144,
          "compute_cap": "6.1"}
# CIM 认得出 N 卡但 nvidia-smi 不可用：CUDA 三项读不到，不许说成「驱动太旧」
_NVIDIA_NO_SMI = {
    "ready": True,
    "vendor": "nvidia",
    "name": "NVIDIA GeForce GTX 1650",
    "driver_version": "546.33",
    "max_cuda_version": "",
    "memory_total_mb": 0,
    "compute_cap": "",
    "adapters": [
        {"name": "NVIDIA GeForce GTX 1650", "vendor": "nvidia", "driver_version": "546.33"}
    ],
}


def _caps(snap: dict[str, Any], **kwargs: Any) -> dict[str, dict[str, Any]]:
    return device_profile.profile(snap, **kwargs)["caps"]


def test_tier_of_requires_nvidia_and_readable_vram() -> None:
    assert device_profile.tier_of("nvidia", 12288) == "mid"
    # 显存读不到（0）不再是「入门档」：那是未知，不是小卡
    assert device_profile.tier_of("nvidia", 0) == "none"
    for vendor in ("amd", "intel", "other", "none", "unknown"):
        assert device_profile.tier_of(vendor, 24576) == "none", vendor


@pytest.mark.parametrize(
    ("snap", "label"),
    [
        (_AMD, "AMD 显卡 · 视频硬编，AI 引擎走 CPU"),
        (_INTEL, "Intel 显卡 · 视频硬编，AI 引擎走 CPU"),
        (_OTHER, "其他显卡 · AI 引擎走 CPU"),
        (_NONE, "未检测到独立显卡"),
        (_PENDING, "显卡探测中…"),
        (_NVIDIA_OK, "主力（12-19GB 显存）"),
        (_NVIDIA_NO_SMI, "NVIDIA 显卡 · 显存信息不可读"),
    ],
)
def test_tier_label_names_the_host_fact(snap: dict[str, Any], label: str) -> None:
    prof = device_profile.profile(snap, cuda_runtime_installed=False)
    assert prof["tier_label"] == label
    assert prof["tier"] == ("mid" if snap is _NVIDIA_OK else "none")


def test_amd_host_recommends_amf_not_cloud() -> None:
    prof = device_profile.profile(_AMD, cuda_runtime_installed=False)
    assert "AMF" in prof["recommendation"]
    assert "NVIDIA CUDA" in prof["recommendation"]
    assert "云端" in prof["recommendation"], "AI 走 CPU 时仍要给出云端这条路"
    prof_intel = device_profile.profile(_INTEL, cuda_runtime_installed=False)
    assert "QSV" in prof_intel["recommendation"]
    prof_other = device_profile.profile(_OTHER, cuda_runtime_installed=False)
    assert "真试编" in prof_other["recommendation"]
    assert device_profile.profile(_NONE, cuda_runtime_installed=False)[
        "recommendation"
    ].startswith("推荐启用云端引擎")
    assert "CPU" in device_profile.profile(_PENDING, cuda_runtime_installed=False)[
        "recommendation"
    ]


@pytest.mark.parametrize("snap", [_AMD, _INTEL, _OTHER, _NONE])
def test_non_nvidia_caps_are_not_ready_with_vendor_hint(snap: dict[str, Any]) -> None:
    caps = _caps(snap, cuda_runtime_installed=True)
    for key in (
        "faster_whisper_gpu",
        "funasr_gpu",
        "indextts2_gpu",
        "vocal_separation_gpu",
        "local_visual_2b",
    ):
        assert caps[key]["ok"] is False and caps[key]["ready"] is False, key
        assert caps[key]["reason"], key
    assert "NVIDIA CUDA" in caps["vocal_separation_gpu"]["hint"]
    assert "仅支持" in caps["vocal_separation_gpu"]["hint"]
    assert "音色克隆" in caps["indextts2_gpu"]["hint"]


def test_pending_snapshot_hints_probing_not_refusal() -> None:
    caps = _caps(_PENDING, cuda_runtime_installed=False)
    assert caps["faster_whisper_gpu"]["hint"] == "显卡状态探测中：转写暂走 CPU"
    assert caps["vocal_separation_gpu"]["hint"] == "显卡状态探测中：人声分离暂走 CPU"
    assert caps["local_visual_4b"]["hint"] == "显卡状态探测中"


def test_every_cap_carries_reason_and_goes_through_the_same_shape() -> None:
    caps = _caps(_NVIDIA_OK, cuda_runtime_installed=True, torch_variant="cuda")
    for key, cap in caps.items():
        assert set(cap) == {"ok", "ready", "hint", "reason"}, key
        assert isinstance(cap["ok"], bool) and isinstance(cap["ready"], bool), key
    assert caps["faster_whisper_gpu"]["reason"] == ""
    assert caps["indextts2_gpu"]["ready"] is True


def test_indextts2_ready_follows_the_tts_venv_torch_variant() -> None:
    """torch cu128 是 tts-venv 的事：变体 cpu 就不许亮 ready，变体 cuda 才 ready。"""
    cpu = _caps(_NVIDIA_OK, cuda_runtime_installed=True, torch_variant="cpu")
    cuda = _caps(_NVIDIA_OK, cuda_runtime_installed=True, torch_variant="cuda")
    assert cpu["indextts2_gpu"]["ok"] is True
    assert cpu["indextts2_gpu"]["ready"] is False
    assert "CPU 轮" in cpu["indextts2_gpu"]["reason"]
    assert cuda["indextts2_gpu"]["ready"] is True
    assert cuda["indextts2_gpu"]["hint"] == ""


def test_gtx10_blocks_torch_stack_but_not_ct2_or_ort() -> None:
    """§3.5 主验收：sm_61 上 whisper 可用、torch 音色克隆永久不可用、分离仍可用。"""
    caps = _caps(
        _GTX10, cuda_runtime_installed=True, torch_variant="cpu",
        separation_ort={"variant": "gpu", "gpu": True, "reason": ""},
    )
    assert caps["faster_whisper_gpu"]["ok"] is True
    assert caps["indextts2_gpu"]["ok"] is False, "sm_61 低于 torch cu128 的 sm_70 下界"
    assert "sm_70" in caps["indextts2_gpu"]["hint"]
    assert caps["vocal_separation_gpu"]["ready"] is True
    assert caps["funasr_gpu"]["ok"] is True, "funasr 不写静态下限（两套运行时实况不同）"


def test_funasr_has_no_static_floor_ready_follows_the_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """老卡（sm_52）上 funasr 可能真在 GPU 跑：静态下限会造假阴性，ready 只看探测。"""
    snap = {**_NVIDIA_OK, "compute_cap": "5.2", "memory_total_mb": 8192}
    monkeypatch.setattr(device_profile, "_SERVICE_TORCH_STATE", (True, True, "5.2"))
    assert _caps(snap, cuda_runtime_installed=True, torch_variant="cpu")[
        "funasr_gpu"
    ]["ready"] is True
    monkeypatch.setattr(device_profile, "_SERVICE_TORCH_STATE", (False, False, ""))
    assert _caps(snap, cuda_runtime_installed=True, torch_variant="cpu")[
        "funasr_gpu"
    ]["ready"] is False


def test_driver_unreadable_is_not_reported_as_too_old() -> None:
    """§3.3：读不到 ≠ 太旧。reason 说「无法确认」，不许冒充 CUDA 上限过低。"""
    prof = device_profile.profile(_NVIDIA_NO_SMI, cuda_runtime_installed=False)
    guidance = prof["driver_guidance"]
    assert guidance["needed"] is True
    assert "未能读取" in guidance["reason"]
    assert "低于 12" not in guidance["reason"]
    assert "nvidia-smi" in guidance["reason"]
    assert "驱动信息不可读" in prof["recommendation"]
    caps = prof["caps"]
    assert caps["faster_whisper_gpu"]["ready"] is False
    assert caps["faster_whisper_gpu"]["hint"] == "未能读取 NVIDIA 驱动信息，无法确认 CUDA 12 支持"


def test_driver_too_old_still_says_so_with_the_number() -> None:
    snap = {**_NVIDIA_OK, "max_cuda_version": "11.8"}
    prof = device_profile.profile(snap, cuda_runtime_installed=False)
    assert prof["driver_guidance"]["needed"] is True
    assert "11.8" in prof["driver_guidance"]["reason"]
    assert "低于 12" in prof["driver_guidance"]["reason"]
    assert "更新 NVIDIA 驱动" in prof["recommendation"]


def test_local_visual_caps_stay_not_ready_for_everyone() -> None:
    """视觉轨的 CUDA 构建资产还没进资产库：任何宿主都不得提前点亮。"""
    for snap in (_NVIDIA_OK, _AMD, _NONE):
        caps = _caps(snap, cuda_runtime_installed=True, torch_variant="cuda")
        for key in ("local_visual_2b", "local_visual_4b", "local_visual_8b"):
            assert caps[key]["ready"] is False, f"{snap['vendor']}/{key}"


def test_local_visual_ok_follows_the_vram_floor() -> None:
    """12GB 的 N 卡够 4B 档、不够 8B 档：显存门槛与厂商无关，只与 N 卡 + 显存有关。"""
    caps = _caps(_NVIDIA_OK, cuda_runtime_installed=True, torch_variant="cuda")
    assert caps["local_visual_2b"]["ok"] is True
    assert caps["local_visual_4b"]["ok"] is True
    assert caps["local_visual_8b"]["ok"] is False
    assert caps["local_visual_8b"]["reason"]

    amd = _caps(_AMD, cuda_runtime_installed=True, torch_variant="cuda")
    assert amd["local_visual_2b"]["ok"] is False
