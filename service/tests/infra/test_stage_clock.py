"""StageClock 契约：顺序记账、异常照记、汇总格式。全部用假时钟做确定性断言。"""

from __future__ import annotations

import pytest

from dramaclip.infra.stage_clock import StageClock


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_records_spans_in_order() -> None:
    clock = _Clock()
    stages = StageClock(clock)
    with stages.stage("转写"):
        clock.now += 10.0
    with stages.stage("语义"):
        clock.now += 58.0
    assert stages.summary() == "转写 10s / 语义 58s"


def test_minutes_format_kicks_in_at_a_minute() -> None:
    clock = _Clock()
    stages = StageClock(clock)
    with stages.stage("转写"):
        clock.now += 192.0
    assert stages.summary() == "转写 3.2m"


def test_exception_still_records_elapsed() -> None:
    clock = _Clock()
    stages = StageClock(clock)
    with pytest.raises(RuntimeError), stages.stage("视觉"):
        clock.now += 7.0
        raise RuntimeError("模型炸了")
    assert stages.summary() == "视觉 7s"


def test_empty_clock_summarizes_to_empty_string() -> None:
    assert StageClock(_Clock()).summary() == ""
