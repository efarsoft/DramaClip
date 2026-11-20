"""d3d_probe IID 常量守卫：GUID 尾段写错一个字节 = E_NOINTERFACE 探测全废。

历史事故（2026-11-20）：_IID_IDXGIFACTORY1 尾段 e7c1c4e5e0b4 写成 e2533473d5e5，
CreateDXGIFactory1 查无此接口回 E_NOINTERFACE，探测静默回退 CIM——D3D 数据源
自落地起从未工作过。沙箱隔离（DXGI 禁访）当时把归因带偏：沙箱炸+真机也炸是
两个独立问题。本测试把常量字节钉死到官方值，防止再犯。"""

from __future__ import annotations

import uuid

from dramaclip.infra import d3d_probe


def test_factory_iid_bytes_match_official() -> None:
    """_IID_IDXGIFACTORY1 产出的 16 字节必须逐字节等于官方 IID 的 bytes_le。"""
    expected = uuid.UUID("770aae78-f26f-4dba-a829-e7c1c4e5e0b4").bytes_le
    guid = d3d_probe._refiid(d3d_probe._IID_IDXGIFACTORY1)
    assert bytes(guid.contents) == expected


def test_refiid_produces_standard_layout() -> None:
    """_refiid 输出标准 GUID 内存布局（Data1/Data2 小端 + Data4 原序）。"""
    # Windows 标准样本：{6B29FC40-CA47-1067-B31D-00DD010662DA}
    guid = d3d_probe._refiid("6B29FC40-CA47-1067-B31D-00DD010662DA")
    assert bytes(guid.contents) == bytes.fromhex("40fc296b47ca6710b31d00dd010662da")
