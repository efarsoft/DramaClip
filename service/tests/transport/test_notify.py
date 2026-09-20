"""Notifier：业务日志的两条命——通知面带 job_id，落盘面按作业可归因。

log.append 一旦被渲染层漏订，业务日志就只剩"当场闪过"；并发任务下没有 job_id
更是无从归因。这里钉的是：作业作用域内的每条日志都带 id、作用域随任务结束复位、
每条日志同时进 Python logger（即 backend.log 轮转文件）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from dramaclip.transport.notify import Notifier


@pytest.fixture()
def sent() -> list[dict[str, Any]]:
    return []


@pytest.fixture()
def notifier(sent: list[dict[str, Any]]) -> Notifier:
    return Notifier(sent.append)


def _params(sent: list[dict[str, Any]], index: int = 0) -> dict[str, Any]:
    notification = sent[index]
    assert notification["method"] == "log.append"
    return dict(notification["params"])


def test_log_outside_any_job_carries_no_job_id(notifier: Notifier, sent: Any) -> None:
    notifier.log("info", "模型目录重新探测完成")
    assert _params(sent) == {"level": "info", "message": "模型目录重新探测完成"}


def test_log_inside_tracked_job_carries_job_id(notifier: Notifier, sent: Any) -> None:
    def work() -> None:
        notifier.log("error", "分析任务失败: 模型加载不了")

    notifier.tracked("job-7", work)()
    assert _params(sent)["job_id"] == "job-7"


def test_explicit_job_id_wins_over_the_scope(notifier: Notifier, sent: Any) -> None:
    def work() -> None:
        notifier.log("warn", "兄弟任务的口径", job_id="job-other")

    notifier.tracked("job-7", work)()
    assert _params(sent)["job_id"] == "job-other"


def test_scope_resets_so_a_reused_worker_thread_stays_clean(
    notifier: Notifier, sent: Any
) -> None:
    """线程池复用工作线程：绑定若随任务结束不复位，下一条任务会冒用旧 job_id。"""

    def work(message: str) -> None:
        notifier.log("info", message)

    with ThreadPoolExecutor(max_workers=1) as pool:
        tracked: Callable[[], None] = notifier.tracked("job-1", work, "任务内")
        pool.submit(tracked).result()
        pool.submit(work, "任务外").result()
    assert "job_id" in _params(sent, 0)
    assert "job_id" not in _params(sent, 1)


def test_tracked_returns_the_payload_of_the_wrapped_call(
    notifier: Notifier, sent: Any
) -> None:
    def work(value: int) -> int:
        return value * 2

    assert notifier.tracked("job-1", work, 21)() == 42


def test_business_log_mirrors_to_the_file_logger_with_job_prefix(
    notifier: Notifier, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        notifier.tracked("job-9", notifier.log, "warn", "导出失败: 响度不达标")()
    lines = [record.message for record in caplog.records]
    assert any("导出失败" in line and line.startswith("[job-9]") for line in lines)
    mirrored = [r for r in caplog.records if "响度不达标" in r.message]
    assert mirrored and mirrored[0].levelno == logging.WARNING


def test_unknown_level_mirrors_as_info(
    notifier: Notifier, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        notifier.log("debug", "没见过的级别")
    assert any("没见过的级别" in record.message for record in caplog.records)
