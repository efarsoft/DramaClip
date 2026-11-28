"""墙钟毫秒单源：库表时间戳与作业台账的 now_ms（原 11 份 _now_ms 手抄的家）。

为什么收这里：同一行 `int(time.time() * 1000)` 在 api/infra/engines 三层各抄了一份，
改语义（比如换时钟源）要挨个同步——11 处逐字节相同的克隆没有并存的理由。

口径纪律：本函数是**墙钟**（epoch 毫秒，会回拨），只用于入库时间戳与排序展示；
量「耗时多久」一律走单调钟（time.monotonic，见 infra.stage_clock）——两个口径
不许混用。同毫秒碰撞是已知事实（背靠背两次调用撞同一值，调用方的排序键自己兜），
收单源不改变这一点。
"""

from __future__ import annotations

import time


def now_ms() -> int:
    """当前墙钟毫秒（epoch）：入库时间戳与台账排序的唯一家。"""
    return int(time.time() * 1000)
