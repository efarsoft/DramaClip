"""d3d_probe IID 常量守卫：GUID 尾段写错一个字节 = E_NOINTERFACE 探测全废。

历史事故两连（2026-11-19/20）：初版尾段 e2533473d5e5 错；首修 e7c1c4e5e0b4
仍是错值（凭记忆未核一手来源）——两版 CreateDXGIFactory1 都回 E_NOINTERFACE，
探测自落地起从未产出过一行数据。终值以 Windows SDK 10.0.26100.0 dxgi.h:3119
DEFINE_GUID 为准（253c83d1b387）。本测试钉的是常量本身；枚举的控制流
（收尾信号、失败留痕）由 test_d3d_probe_enum.py 用假 COM 对象验——只有字节
断言的那段时间，第三、四个缺陷（HRESULT restype 吞清单）就是从缝里漏过去的。
"""

from __future__ import annotations

import uuid

from dramaclip.infra import d3d_probe


def test_factory_iid_bytes_match_official() -> None:
    """_IID_IDXGIFACTORY1 产出的 16 字节必须逐字节等于官方 IID 的 bytes_le。"""
    expected = uuid.UUID("770aae78-f26f-4dba-a829-253c83d1b387").bytes_le
    guid = d3d_probe._refiid(d3d_probe._IID_IDXGIFACTORY1)
    assert bytes(guid.contents) == expected


def test_refiid_produces_standard_layout() -> None:
    """_refiid 输出标准 GUID 内存布局（Data1/Data2 小端 + Data4 原序）。"""
    # Windows 标准样本：{6B29FC40-CA47-1067-B31D-00DD010662DA}
    guid = d3d_probe._refiid("6B29FC40-CA47-1067-B31D-00DD010662DA")
    assert bytes(guid.contents) == bytes.fromhex("40fc296b47ca6710b31d00dd010662da")
