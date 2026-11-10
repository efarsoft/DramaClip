"""任务级 LLM 等待预算（第一梯队⑤）：只计「等云端响应」的墙钟时间。

此前单任务 LLM 累计等待无上限——端点「慢死」（连接活着、每秒有字节、但
一次调用要几分钟）时 240s 档超时形同虚设，几十段文案能把任务拖到小时级
还占着执行池。本模块给任务挂一个只计云端等待的预算：

- ``budget(seconds)``：任务入口挂预算（嵌套时取更紧的剩余值，不放大）；
- ``paused()``：本地 CPU/渲染段冻结计时——超时分母是云端延迟，ffmpeg
  跑几分钟不该吃掉 LLM 预算；
- ``check_and_timeout(requested)``：LLM 调用前把 read 超时压到剩余预算
  （单次调用不可能超出预算），耗尽抛 :class:`LlmBudgetExceeded`。

线程语义：预算存 threading.local——导出任务在执行池单线程跑全链，LLM
调用同线程可见；无预算上下文的调用（引擎自检/工具箱/查询池）不受限。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

_STATE = threading.local()


class LlmBudgetExceeded(RuntimeError):
    """任务级 LLM 等待预算耗尽：任务该失败并明说原因，不是继续磨。"""


def _deadline() -> float | None:
    return getattr(_STATE, "deadline", None)


@contextmanager
def budget(seconds: float) -> Iterator[None]:
    """开启预算窗口；嵌套时取更紧的截止（子窗口不能放大外层预算）。"""
    outer = _deadline()
    inner = time.monotonic() + seconds
    saved = outer
    _STATE.deadline = inner if outer is None else min(outer, inner)
    try:
        yield
    finally:
        _STATE.deadline = saved


@contextmanager
def paused() -> Iterator[None]:
    """本地 CPU/渲染段冻结计时：退出时把截止重设为「现在 + 剩余」。"""
    outer = _deadline()
    if outer is None:
        yield  # 无预算上下文：空操作
        return
    remaining = outer - time.monotonic()
    _STATE.deadline = None  # 冻结：段内 check 不受限（本就没有 LLM 调用）
    try:
        yield
    finally:
        _STATE.deadline = time.monotonic() + max(remaining, 0.0)


def open_budget(seconds: float) -> float | None:
    """非 with 版开启：返回需回传 close_budget 的旧截止；嵌套取更紧值。"""
    outer = _deadline()
    inner = time.monotonic() + seconds
    _STATE.deadline = inner if outer is None else min(outer, inner)
    return outer


def close_budget(saved: float | None) -> None:
    """配对 open_budget 的恢复（任务 finally 里调用，异常路径也不泄漏）。"""
    _STATE.deadline = saved


def remaining() -> float | None:
    """剩余预算秒数；无预算上下文返回 None（不限制）。"""
    outer = _deadline()
    if outer is None:
        return None
    return outer - time.monotonic()


def check_and_timeout(requested: float) -> float:
    """LLM 调用前的 read 超时取「请求值与剩余预算」的较小者。

    耗尽抛 :class:`LlmBudgetExceeded`——由任务层转成明确的失败理由。
    """
    left = remaining()
    if left is None:
        return requested
    if left <= 0:
        raise LlmBudgetExceeded("任务级 LLM 等待预算已耗尽")
    return min(requested, left)
