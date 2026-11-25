"""宿主 GPU 探测的多厂商事实：CIM 枚举 + nvidia-smi 合并，虚拟适配器不算显卡。

判据是「宿主有什么卡」，不是「有没有 N 卡」——AMD/Intel 主机的 vendor 必须如实，
否则界面与设备选项都会把有卡的主机报成无卡（规格 §1 根因 1/6）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

import pytest

from dramaclip.infra import gpu


def test_classify_vendor_by_name_prefix_order() -> None:
    assert gpu.classify_vendor("NVIDIA GeForce RTX 3060") == "nvidia"
    assert gpu.classify_vendor("Quadro M4000") == "nvidia"
    assert gpu.classify_vendor("Radeon (TM) RX 6600") == "amd"
    assert gpu.classify_vendor("AMD Radeon Graphics") == "amd"
    assert gpu.classify_vendor("ATI Radeon X1900") == "amd"
    assert gpu.classify_vendor("Intel(R) UHD Graphics 770") == "intel"
    assert gpu.classify_vendor("Some Unknown 3D Controller") == "other"
    assert gpu.classify_vendor("") == "other"


def test_virtual_adapters_are_filtered() -> None:
    for name in (
        "Microsoft Basic Display Adapter",
        "Microsoft Basic Render Driver",
        "Microsoft Remote Display Adapter",
        "Microsoft Hyper-V Video",
        "VMware SVGA II Adapter",
        "VirtualBox Graphics Adapter",
        "Parsec Virtual Display Adapter",
        "Citrix Workspace Assistant Display",
        "GameViewer Virtual Display Adapter",
        "Mirage MQ Helper",
    ):
        assert gpu.is_virtual_adapter(name), name
    assert not gpu.is_virtual_adapter("AMD Radeon RX 6600")
    assert not gpu.is_virtual_adapter("Intel(R) Iris(R) Xe Graphics")


def test_parse_cim_output_accepts_single_object_and_array() -> None:
    single = json.dumps({"Name": "AMD Radeon RX 6600", "DriverVersion": "31.0.12027.9001"})
    assert gpu.parse_cim_output(single) == [
        {"name": "AMD Radeon RX 6600", "vendor": "amd", "driver_version": "31.0.12027.9001"}
    ]
    array = json.dumps(
        [
            {"Name": "Intel(R) UHD Graphics 770", "DriverVersion": "31.0.101.5333"},
            {"Name": "GameViewer Virtual Display Adapter", "DriverVersion": "1.0.0"},
        ]
    )
    # 虚拟设备在 parse 阶段就剔除：调用方不需要再记一遍过滤规则
    assert gpu.parse_cim_output(array) == [
        {"name": "Intel(R) UHD Graphics 770", "vendor": "intel", "driver_version": "31.0.101.5333"}
    ]


def test_parse_cim_output_tolerates_bom_and_missing_fields() -> None:
    raw = '﻿[{"Name": "AMD Radeon RX 6600"}]'
    assert gpu.parse_cim_output(raw) == [
        {"name": "AMD Radeon RX 6600", "vendor": "amd", "driver_version": ""}
    ]


def test_parse_cim_output_rejects_illegal_json() -> None:
    with pytest.raises(ValueError):
        gpu.parse_cim_output("not json at all")


def test_choose_primary_prefers_nvidia_then_amd_then_intel() -> None:
    adapters = [
        {"name": "Intel(R) UHD Graphics 770", "vendor": "intel", "driver_version": "31.0"},
        {"name": "AMD Radeon RX 6600", "vendor": "amd", "driver_version": "31.0"},
        {"name": "NVIDIA GeForce RTX 3060", "vendor": "nvidia", "driver_version": "551.61"},
    ]
    assert gpu.choose_primary(adapters)["name"] == "NVIDIA GeForce RTX 3060"
    without_nvidia = [a for a in adapters if a["vendor"] != "nvidia"]
    assert gpu.choose_primary(without_nvidia)["name"] == "AMD Radeon RX 6600"
    assert gpu.choose_primary([adapters[0]])["name"] == "Intel(R) UHD Graphics 770"
    other_only = [{"name": "USB 3D Hub", "vendor": "other", "driver_version": ""}]
    assert gpu.choose_primary(other_only) == other_only[0]
    assert gpu.choose_primary([]) is None


def test_choose_primary_keeps_cim_order_within_same_vendor() -> None:
    adapters = [
        {"name": "AMD Radeon RX 6600", "vendor": "amd", "driver_version": "1"},
        {"name": "AMD Radeon Pro W5700", "vendor": "amd", "driver_version": "2"},
    ]
    assert gpu.choose_primary(adapters)["name"] == "AMD Radeon RX 6600"


def _stub_queries(
    monkeypatch: pytest.MonkeyPatch,
    cim: Any,
    smi: Any,
    platform: str = "win32",
    d3d: Any = None,
) -> None:
    monkeypatch.setattr(gpu.sys, "platform", platform, raising=False)
    monkeypatch.setattr(gpu, "_query_cim_adapters", cim)
    monkeypatch.setattr(gpu, "_query_nvidia_smi", smi)
    # DXGI 枚举也必须打桩：它自 2026-11-24 修好后能真的枚举到本机显卡，不打桩的话
    # 这些用例测的就是开发机而不是「设定的宿主」。
    monkeypatch.setattr(gpu.d3d_probe, "enumerate_adapters", d3d or (lambda: []))


def _dxgi(
    name: str, vendor_id: int, device_id: int, video_mb: int, **flags: Any
) -> dict[str, Any]:
    """d3d_probe.enumerate_adapters 的一条产出（形状与真实枚举一致）。"""
    return {
        "name": name,
        "vendor_id": f"0x{vendor_id:04x}",
        "vendor": gpu.classify_vendor("", vendor_id),
        "device_id": f"0x{device_id:04x}",
        "dedicated_video_mb": video_mb,
        "is_software": flags.get("is_software", False),
        "is_virtual": flags.get("is_virtual", False),
    }


def test_detect_reports_amd_host_with_adapters_and_empty_cuda_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapters = [{"name": "AMD Radeon RX 6600", "vendor": "amd", "driver_version": "31.0.12027"}]
    _stub_queries(monkeypatch, lambda: adapters, lambda: None)
    info = gpu.detect()
    assert info["ready"] is True
    assert info["vendor"] == "amd"
    assert info["name"] == "AMD Radeon RX 6600"
    assert info["driver_version"] == "31.0.12027"
    # 非 N 卡不采信 AdapterRAM：显存宁可为 0，不写假数（规格 §2.1）
    assert info["memory_total_mb"] == 0
    assert info["max_cuda_version"] == ""
    assert info["compute_cap"] == ""
    assert info["adapters"] == adapters


def test_detect_nvidia_smi_overrides_cim_nvidia_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cim = [{"name": "NVIDIA GeForce RTX 3060", "vendor": "nvidia", "driver_version": "546.00"}]
    smi = {
        "name": "NVIDIA GeForce RTX 3060",
        "driver_version": "551.61",
        "memory_total_mb": 12288,
        "max_cuda_version": "12.4",
        "compute_cap": "8.6",
    }
    _stub_queries(monkeypatch, lambda: cim, lambda: smi)
    info = gpu.detect()
    assert info["vendor"] == "nvidia"
    assert info["driver_version"] == "551.61", "CUDA 细节只来自 nvidia-smi"
    assert info["memory_total_mb"] == 12288
    assert info["max_cuda_version"] == "12.4"
    assert info["adapters"][0]["driver_version"] == "551.61"


def test_detect_adds_nvidia_adapter_when_only_smi_sees_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cim = [{"name": "Intel(R) UHD Graphics 770", "vendor": "intel", "driver_version": "31.0"}]
    smi = {
        "name": "NVIDIA GeForce RTX 4060",
        "driver_version": "552.22",
        "memory_total_mb": 8192,
        "max_cuda_version": "12.4",
        "compute_cap": "8.9",
    }
    _stub_queries(monkeypatch, lambda: cim, lambda: smi)
    info = gpu.detect()
    assert info["vendor"] == "nvidia", "主适配器优先级 NVIDIA > Intel"
    assert [a["vendor"] for a in info["adapters"]] == ["nvidia", "intel"]


def test_detect_cim_only_nvidia_leaves_cuda_fields_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CIM 看得到 N 卡但 nvidia-smi 不可用：vendor 如实 nvidia，CUDA 三项为空——不得据此判驱动旧。"""
    cim = [{"name": "NVIDIA GeForce GTX 1650", "vendor": "nvidia", "driver_version": "546.33"}]
    _stub_queries(monkeypatch, lambda: cim, lambda: None)
    info = gpu.detect()
    assert info["vendor"] == "nvidia"
    assert info["name"] == "NVIDIA GeForce GTX 1650"
    assert info["driver_version"] == "546.33"
    assert info["max_cuda_version"] == ""
    assert info["memory_total_mb"] == 0
    assert info["compute_cap"] == ""


def test_detect_cim_failure_still_uses_smi(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> list[dict[str, str]]:
        raise RuntimeError("powershell 不存在")

    smi = {
        "name": "NVIDIA T400",
        "driver_version": "551.61",
        "memory_total_mb": 4096,
        "max_cuda_version": "12.4",
        "compute_cap": "7.5",
    }
    _stub_queries(monkeypatch, boom, lambda: smi)
    info = gpu.detect()
    assert info["vendor"] == "nvidia"
    assert info["adapters"] == [
        {"name": "NVIDIA T400", "vendor": "nvidia", "driver_version": "551.61"}
    ]


def test_detect_no_adapter_at_all_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_queries(monkeypatch, lambda: [], lambda: None)
    info = gpu.detect()
    assert info["vendor"] == "none"
    assert info["adapters"] == []


def test_detect_non_windows_skips_cim(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    _stub_queries(
        monkeypatch,
        lambda: calls.append(1) or [],
        lambda: None,
        platform="darwin",
    )
    info = gpu.detect()
    assert calls == []
    assert info["vendor"] == "none"


def test_detect_prefers_dxgi_identity_and_keeps_one_row_per_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DXGI 可用时以它为主：厂商按 PCI ID、显存来自 DXGI；同一块物理卡的多个呈现
    实例只留一条（M4000 开发机实测：DXGI 把同一块 Radeon 报了 3~4 条）。"""
    cim = [
        {"name": "Radeon RX 5500 XT", "vendor": "amd", "driver_version": "27.20.21003"},
        {"name": "Quadro M4000", "vendor": "nvidia", "driver_version": "552.22"},
        {"name": "OrayIddDriver Device", "vendor": "other", "driver_version": "1.0.0.0"},
    ]
    radeon = _dxgi("Radeon RX 5500 XT", 0x1002, 0x7340, 8151)
    d3d = [
        dict(radeon),
        _dxgi("NVIDIA Quadro M4000", 0x10DE, 0x13F1, 8132),
        dict(radeon),
        dict(radeon),
        _dxgi("Microsoft Basic Render Driver", 0x1414, 0x008C, 0, is_software=True),
    ]
    _stub_queries(monkeypatch, lambda: cim, lambda: None, d3d=lambda: d3d)

    info = gpu.detect()

    assert [a["name"] for a in info["adapters"]] == [
        "Radeon RX 5500 XT",
        "NVIDIA Quadro M4000",
        "OrayIddDriver Device",
    ]
    amd_row, nvidia_row, other_row = info["adapters"]
    assert amd_row["driver_version"] == "27.20.21003"  # CIM 按名称补驱动版本
    assert amd_row["vendor_id"] == "0x1002" and amd_row["dedicated_video_mb"] == 8151
    # 名称差一个厂商前缀也认得出是同一块卡——否则它会以两个名字各出现一行
    assert nvidia_row["driver_version"] == "552.22"
    assert other_row["driver_version"] == "1.0.0.0"  # CIM 独有的适配器照常追加
    assert info["vendor"] == "nvidia"
    assert info["name"] == "NVIDIA Quadro M4000"


def test_detect_dxgi_vendor_id_decides_vendor(monkeypatch: pytest.MonkeyPatch) -> None:
    """名称里一个厂商 token 都没有的卡，厂商以 PCI ID 为准，显存也来自 DXGI。"""
    d3d = [_dxgi("Some 3D Controller", 0x8086, 0x5690, 4096)]
    _stub_queries(monkeypatch, lambda: [], lambda: None, d3d=lambda: d3d)

    info = gpu.detect()

    assert info["vendor"] == "intel"
    assert info["adapters"][0]["dedicated_video_mb"] == 4096


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="CIM 枚举是 Windows 专属 API，Linux 早退空表是设计内行为",
)
def test_parse_cim_command_is_fixed_and_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen["cmd"] = cmd
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, '[{"Name":"AMD Radeon RX 6600"}]', "")

    monkeypatch.setattr(gpu.subprocess, "run", fake_run)
    out = gpu._query_cim_adapters()  # noqa: SLF001
    assert out == [{"name": "AMD Radeon RX 6600", "vendor": "amd", "driver_version": ""}]
    joined = " ".join(seen["cmd"])
    assert "Win32_VideoController" in joined
    assert "DriverVersion" in joined
    assert "Name" in joined
    assert "AdapterRAM" not in joined, "AdapterRAM 是 UInt32，现代显卡普遍失真，不采信"
    assert seen["timeout"] == 10.0
    assert seen["creationflags"] == gpu._NO_WINDOW  # noqa: SLF001


def test_query_cim_adapters_swallows_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(["powershell.exe"], 10)

    monkeypatch.setattr(gpu.subprocess, "run", boom)
    assert gpu._query_cim_adapters() == []  # noqa: SLF001


def test_snapshot_pending_shape_includes_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gpu, "_CACHE", None, raising=False)
    monkeypatch.setattr(gpu, "prefetch", lambda: None)
    snap = gpu.snapshot()
    assert snap["ready"] is False
    assert snap["vendor"] == "unknown"
    assert snap["adapters"] == []
