"""DXGI 枚举的行为回归：用假 COM 对象（vtable 可控）把整条枚举路径端到端跑一遍。

背景（2026-11-24 审查实锤）：ctypes.HRESULT 当 restype 时，失败码会直接抛
OSError 而不是返回；枚举循环却靠「返回值 != 0」收尾。于是枚举完最后一个
适配器后的 DXGI_ERROR_NOT_FOUND 被抛成异常，跳过 return、已收齐的清单整个
丢弃——该函数自落地起从未返回过非空清单。此前只有字节级常量断言，拦不住
这类控制流错误；本测试验的是行为。

假对象不依赖 Windows、不依赖显卡（Linux CI 照跑）：非 Windows 平台把
WINFUNCTYPE 换成 CFUNCTYPE——这里验的是控制流，不是调用约定。
"""

from __future__ import annotations

import ctypes
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.infra import d3d_probe

# 有符号 32 位的失败码（ctypes 在 Windows 上以 c_long 收，负数）
_DXGI_ERROR_NOT_FOUND = 0x887A0002 - (1 << 32)
_E_NOINTERFACE = 0x80004002 - (1 << 32)
_SOFTWARE_ADAPTER_FLAG = 2  # DXGI_ADAPTER_FLAG_SOFTWARE


class _FakeObject(ctypes.Structure):
    """最小 COM 对象形态：首字段指向 vtable（函数指针表）。"""

    _fields_ = [("vtbl", ctypes.POINTER(ctypes.c_void_p))]


def _functype() -> Any:
    return getattr(ctypes, "WINFUNCTYPE", None) or ctypes.CFUNCTYPE


def _install_fake_dxgi(
    monkeypatch: pytest.MonkeyPatch,
    *,
    adapters: list[dict[str, int | str]],
    factory_hr: int = 0,
    fail_at_index: int | None = None,
) -> SimpleNamespace:
    """装上一套假的 dxgi.dll：CreateDXGIFactory1 返回假工厂，其 vtable[12]
    按序号吐出假适配器，取完返回 NOT_FOUND。返回值只带各对象的释放记录。"""
    if not hasattr(ctypes, "WINFUNCTYPE"):
        monkeypatch.setattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE, raising=False)
    func = _functype()
    keep: list[Any] = []
    released: list[str] = []

    @func(ctypes.c_long, ctypes.c_void_p)
    def release(self: int) -> int:
        released.append("adapter")
        return 0

    @func(ctypes.c_long, ctypes.c_void_p)
    def release_factory(self: int) -> int:
        released.append("factory")
        return 0

    keep += [release, release_factory]

    def make_adapter(spec: dict[str, int | str]) -> _FakeObject:
        @func(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(d3d_probe._AdapterDesc1))
        def get_desc(self: int, out: Any) -> int:
            out[0].Description = str(spec["name"])
            out[0].VendorId = int(spec["vendor_id"])
            out[0].DeviceId = int(spec["device_id"])
            out[0].DedicatedVideoMemory = int(spec["dedicated_video_mb"]) * 1024 * 1024
            out[0].Flags = int(spec.get("flags", 0))
            return 0

        keep.append(get_desc)
        table = (ctypes.c_void_p * 16)()
        table[d3d_probe._VT_RELEASE] = ctypes.cast(release, ctypes.c_void_p)
        table[d3d_probe._VT_GETDESC1] = ctypes.cast(get_desc, ctypes.c_void_p)
        keep.append(table)  # 假对象的字段只是指向 vtable 的裸指针，数组本身也得活着
        return _FakeObject(ctypes.cast(table, ctypes.POINTER(ctypes.c_void_p)))

    adapter_objects = [make_adapter(spec) for spec in adapters]
    adapter_pointers = [ctypes.c_void_p(ctypes.addressof(obj)) for obj in adapter_objects]
    keep += adapter_objects + adapter_pointers

    factory_holder: dict[str, _FakeObject] = {}

    @func(
        ctypes.c_long,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.POINTER(ctypes.c_void_p),
    )
    def enum_adapters(self: int, index: int, out: Any) -> int:
        if fail_at_index is not None and index == fail_at_index:
            return 0x887A0005 - (1 << 32)  # DXGI_ERROR_DEVICE_REMOVED：中途出错
        if index < len(adapter_pointers):
            out[0] = adapter_pointers[index]
            return 0
        return _DXGI_ERROR_NOT_FOUND

    keep.append(enum_adapters)

    @func(ctypes.c_long, ctypes.POINTER(d3d_probe._GUID), ctypes.POINTER(ctypes.c_void_p))
    def create_factory(riid: Any, out: Any) -> int:
        if factory_hr != 0:
            return factory_hr
        out[0] = ctypes.c_void_p(ctypes.addressof(factory_holder["factory"]))
        return 0

    keep.append(create_factory)

    factory_table = (ctypes.c_void_p * 16)()
    factory_table[d3d_probe._VT_RELEASE] = ctypes.cast(release_factory, ctypes.c_void_p)
    factory_table[d3d_probe._VT_ENUM_ADAPTERS1] = ctypes.cast(enum_adapters, ctypes.c_void_p)
    keep.append(factory_table)
    factory_holder["factory"] = _FakeObject(
        ctypes.cast(factory_table, ctypes.POINTER(ctypes.c_void_p))
    )
    keep.append(factory_holder["factory"])

    class _FakeDll:
        CreateDXGIFactory1 = create_factory

        # 回调、vtable、假对象全部挂在这个补丁类上：monkeypatch 持有它的引用直到用例
        # 结束，调用方不必保存本函数的返回值。ctypes 回调一旦被回收，vtable 里就是
        # 野指针（实测症状：访问冲突 / 「不是可调用的函数地址」）。
        _keep = keep

    monkeypatch.setattr(ctypes, "WinDLL", lambda _name: _FakeDll(), raising=False)
    return SimpleNamespace(released=released)


_NVIDIA = {
    "name": "NVIDIA Quadro M4000",
    "vendor_id": 0x10DE,
    "device_id": 0x13F1,
    "dedicated_video_mb": 8132,
}
_INTEL = {
    "name": "Intel(R) Arc(TM) A770 Graphics",
    "vendor_id": 0x8086,
    "device_id": 0x5690,
    "dedicated_video_mb": 16268,
}
_SOFTWARE = {
    "name": "Microsoft Basic Render Driver",
    "vendor_id": 0x1414,
    "device_id": 0x008C,
    "dedicated_video_mb": 0,
    "flags": _SOFTWARE_ADAPTER_FLAG,
}
_VMWARE = {
    "name": "VMware SVGA II",
    "vendor_id": 0x15AD,
    "device_id": 0x0405,
    "dedicated_video_mb": 0,
}


def test_enum_returns_every_adapter_and_stops_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = _install_fake_dxgi(monkeypatch, adapters=[_NVIDIA, _INTEL])

    result = d3d_probe._enum_win32()

    assert [item["name"] for item in result] == ["NVIDIA Quadro M4000", _INTEL["name"]]
    nvidia, intel = result
    assert (nvidia["vendor"], nvidia["vendor_id"], nvidia["device_id"]) == (
        "nvidia",
        "0x10de",
        "0x13f1",
    )
    assert nvidia["dedicated_video_mb"] == 8132
    assert nvidia["is_software"] is False and nvidia["is_virtual"] is False
    assert intel["vendor"] == "intel" and intel["dedicated_video_mb"] == 16268
    # 每个适配器与工厂各释放一次，不多不少
    assert fake.released == ["adapter", "adapter", "factory"]
    # 收尾的 NOT_FOUND 是正常结束：不许留「枚举失败」的现场
    assert "DXGI" not in capsys.readouterr().err


def test_zero_adapters_is_an_empty_list_not_an_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_fake_dxgi(monkeypatch, adapters=[])

    assert d3d_probe._enum_win32() == []
    assert "DXGI" not in capsys.readouterr().err


def test_software_and_virtual_adapters_are_flagged_not_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_dxgi(monkeypatch, adapters=[_SOFTWARE, _VMWARE])

    result = d3d_probe._enum_win32()

    assert [(item["is_software"], item["is_virtual"]) for item in result] == [
        (True, False),
        (False, True),
    ]


def test_factory_creation_failure_leaves_a_trace(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_fake_dxgi(monkeypatch, adapters=[_NVIDIA], factory_hr=_E_NOINTERFACE)

    assert d3d_probe._enum_win32() == []
    # IID 写错那次就是在这里静默返回了空清单——失败码必须留痕
    assert "CreateDXGIFactory1 失败 hr=0x80004002" in capsys.readouterr().err


def test_midway_failure_keeps_what_was_enumerated_and_traces(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_fake_dxgi(monkeypatch, adapters=[_NVIDIA, _INTEL], fail_at_index=1)

    result = d3d_probe._enum_win32()

    assert [item["name"] for item in result] == ["NVIDIA Quadro M4000"]
    assert "EnumAdapters1(1) 失败 hr=0x887A0005" in capsys.readouterr().err


@pytest.mark.skipif(sys.platform == "win32", reason="非 Windows 平台入口直接返回空清单")
def test_public_entry_is_empty_off_windows() -> None:
    assert d3d_probe.enumerate_adapters() == []


@pytest.mark.skipif(sys.platform != "win32", reason="只在 Windows 上有真实 dxgi.dll")
def test_public_entry_survives_real_dxgi() -> None:
    """真机冒烟：不要求枚举到显卡（无头环境可以是零个），只要求不抛、形状合法。"""
    result = d3d_probe.enumerate_adapters()
    assert isinstance(result, list)
    for item in result:
        assert set(item) == {
            "name",
            "vendor_id",
            "vendor",
            "device_id",
            "dedicated_video_mb",
            "is_software",
            "is_virtual",
        }
