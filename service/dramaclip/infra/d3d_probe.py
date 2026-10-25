"""D3D/DXGI 适配器枚举：厂商/设备 PCI ID + 专用显存（ctypes 直呼，零第三方依赖）。

与 CIM（名称+驱动版本）互补：DXGI 给的 VendorId/DeviceId 是 PCI 身份——厂商判定
不再依赖名称 token，DedicatedVideoMemory 补齐「显存只有 nvidia-smi 才有」的盲区。
PCI 厂商 ID 表即 D3D 层惯例值：AMD=0x1002、NVIDIA=0x10DE、Intel=0x8086；虚拟机
显卡（VMware 0x15AD 等）与软件适配器（WARP flag）标记剔除。任何加载/COM 失败
返回空清单——探测不许拖垮服务，上层回退 CIM 路径。
"""

from __future__ import annotations

import ctypes
import sys
import traceback
import uuid

_PCI_VENDOR_NAMES = {0x1002: "amd", 0x10DE: "nvidia", 0x8086: "intel"}
_VIRTUAL_IDS = {0x15AD}  # VMware SVGA：CIM 名称过滤之外的第二个信号

_IID_IDXGIFACTORY1 = "770aae78-f26f-4dba-a829-e2533473d5e5"
_VT_RELEASE = 2
_VT_ENUM_ADAPTERS1 = 8  # IDXGIFactory1
_VT_GETDESC1 = 10  # IDXGIAdapter1


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _AdapterDesc1(ctypes.Structure):
    """DXGI_ADAPTER_DESC1（x64）：Description 128 wchar + 五个 UINT + 三个 SIZE_T + LUID。"""

    _fields_ = [
        ("Description", ctypes.c_wchar * 128),
        ("VendorId", ctypes.c_uint),
        ("DeviceId", ctypes.c_uint),
        ("SubSysId", ctypes.c_uint),
        ("Revision", ctypes.c_uint),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("LuidLowPart", ctypes.c_uint),
        ("LuidHighPart", ctypes.c_int),
        ("Flags", ctypes.c_uint),
    ]


def _refiid(s: str) -> ctypes.POINTER(_GUID):
    return ctypes.pointer(_GUID.from_buffer_copy(uuid.UUID(s).bytes_le))


def _vtbl_func(ptr: int, index: int, restype: object, *argtypes: object) -> object:
    table = ctypes.cast(
        ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p)).contents.value,
        ctypes.POINTER(ctypes.c_void_p),
    )
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(table[index])


def _clean_name(raw: str) -> str:
    return (raw or "").split("\x00", 1)[0].strip()


def _enum_win32() -> list[dict[str, object]]:
    dxgi = ctypes.WinDLL("dxgi")
    create = dxgi.CreateDXGIFactory1
    create.restype = ctypes.HRESULT
    create.argtypes = [ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
    factory = ctypes.c_void_p()
    if create(_refiid(_IID_IDXGIFACTORY1), ctypes.byref(factory)) != 0 or not factory:
        return []
    try:
        enum_adapters = _vtbl_func(
            factory, _VT_ENUM_ADAPTERS1, ctypes.HRESULT, ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p),
        )
        adapters: list[dict[str, object]] = []
        index = 0
        while True:
            adapter = ctypes.c_void_p()
            if enum_adapters(factory, index, ctypes.byref(adapter)) != 0 or not adapter:
                break
            index += 1
            try:
                get_desc = _vtbl_func(
                    adapter, _VT_GETDESC1, ctypes.HRESULT, ctypes.POINTER(_AdapterDesc1),
                )
                desc = _AdapterDesc1()
                if get_desc(adapter, ctypes.byref(desc)) != 0:
                    continue
                vendor_id = int(desc.VendorId)
                name = _clean_name(desc.Description)
                adapters.append(
                    {
                        "name": name,
                        "vendor_id": f"0x{vendor_id:04x}",
                        "vendor": _PCI_VENDOR_NAMES.get(vendor_id, "other"),
                        "device_id": f"0x{int(desc.DeviceId):04x}",
                        "dedicated_video_mb": int(
                            desc.DedicatedVideoMemory // (1024 * 1024)
                        ),
                        "is_software": bool(desc.Flags & 2),  # DXGI_ADAPTER_FLAG_SOFTWARE
                        "is_virtual": vendor_id in _VIRTUAL_IDS,
                    }
                )
            finally:
                release = _vtbl_func(adapter, _VT_RELEASE, ctypes.HRESULT)
                release(adapter)
        return adapters
    finally:
        release_factory = _vtbl_func(factory, _VT_RELEASE, ctypes.HRESULT)
        release_factory(factory)


def enumerate_adapters() -> list[dict[str, object]]:
    """DXGI 枚举显示适配器；非 Windows 或任何失败返回空清单（上层回退 CIM）。

    每项：name / vendor_id / vendor（PCI ID 判定，认不出 other）/ device_id /
    dedicated_video_mb / is_software / is_virtual。软件适配器与虚拟机显卡不剔除
    （调用方按自己的口径过滤），但都带上了判定字段。
    """
    if sys.platform != "win32":
        return []
    try:
        return _enum_win32()
    except Exception:  # noqa: BLE001 - COM/驱动的任何意外都不许拖垮探测
        # 静默空清单会让「为什么没有 XPU 选项」无从排查：stderr 留一行现场
        print("[d3d-probe] DXGI 枚举失败，回退 CIM：", file=sys.stderr)
        traceback.print_exc()
        return []
