"""api/models.download 的任务生命周期：`model_download` 必须**建在 running 上**。

看门狗收尾只认 running：停在 pending 的任务下载成功也无人回写，队列页永远显示「下载中」；
崩溃残留另由启动清扫复位（见 `infra/jobs.py::sweep_interrupted`）。下载器全程打桩，不触网。
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from dramaclip.api import models as models_api
from dramaclip.infra import jobs as jobs_mod
from dramaclip.infra.model_manager import downloader
from dramaclip.transport.notify import Notifier

_MODEL_ID = "faster-whisper-base"


class _StubDownload:
    """下载替身：记下调用参数，完成时机（on_done）由测试自己按；并登记看门狗线程。

    必须登记而不是按线程名去 enumerate 找：本文件的用例都会起一条 `dl-watch-*`，
    按名字找会 join 到**别的用例**留下的、还阻塞在自己 done_event 上的僵尸线程。
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.on_done = threading.Event()
        self.cancel: threading.Event | None = None
        self.watchdogs: list[threading.Thread] = []

    def __call__(
        self,
        spec: object,
        models_dir: Path,
        notifier: Notifier,
        cancel: threading.Event,
        on_done: threading.Event,
        **kwargs: object,
    ) -> None:
        self.calls.append({"spec": spec, "models_dir": models_dir, "cancel": cancel, **kwargs})
        self.cancel = cancel
        self.on_done = on_done


def _context(memory_db: sqlite3.Connection, tmp_path: Path) -> SimpleNamespace:
    """models.download 用到的最小上下文：job_store + 取消事件表 + 通知器。"""
    return SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        settings={},
        job_store=jobs_mod.JobStore(memory_db),
        cancel_events={},
        notifier=Notifier(lambda _m: None),
    )


@pytest.fixture
def stub_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[_StubDownload]:
    stub = _StubDownload()
    monkeypatch.setattr(downloader, "download_in_background", stub)
    yield stub
    # 每个用例都会经 _download 起一条真看门狗线程，阻塞在 done_event 上。
    # 收尾统一放行并 join，否则僵尸线程会带着自己的连接活到下一个用例。
    stub.on_done.set()
    for watchdog in stub.watchdogs:
        watchdog.join(5.0)


def _download(
    context: SimpleNamespace, stub: _StubDownload, model_id: str = _MODEL_ID
) -> str:
    """返回 job_id，顺带登记本次起的看门狗线程。

    看门狗是 api/models.py 内部起的，起线程发生在 download() 返回之前，
    所以调用前后各取一次线程快照即可精确拿到本次那一条。
    """
    before = {t.name for t in threading.enumerate()}
    try:
        job_id = str(models_api.download(context, {"model_id": model_id})["job_id"])
    finally:
        # 无论成功还是断言失败都要登记：漏登记的看门狗会带着已关闭的连接活到下一个用例。
        stub.watchdogs.extend(
            t
            for t in threading.enumerate()
            if t.name not in before and t.name.startswith("dl-watch-")
        )
    return job_id


def test_download_creates_job_in_running_state(
    memory_db: sqlite3.Connection, tmp_path: Path, stub_download: _StubDownload
) -> None:
    """核心守卫：任务建出来就是 running，不是 pending。

    看门狗的回写条件只认 running：停在 pending 的任务下载成功也无人收尾，队列页永远
    显示「下载中」。崩溃残留另由启动清扫复位（sweep_interrupted）。
    """
    context = _context(memory_db, tmp_path)

    job_id = _download(context, stub_download)

    job = context.job_store.get(job_id)
    assert job is not None
    assert job["type"] == "model_download"
    assert job["ref_id"] == _MODEL_ID
    assert (
        job["status"] == jobs_mod.STATUS_RUNNING
    ), "model_download 必须建在 running 上，否则下载完成后永远停在 pending 且重启清不掉"
    # 取消入口同时注册：jobs.cancel 只有拿到事件才敢回 cancelling=true
    assert job_id in context.cancel_events
    assert context.cancel_events[job_id] is stub_download.cancel


def test_watchdog_completes_running_job_on_download_done(
    memory_db: sqlite3.Connection, tmp_path: Path, stub_download: _StubDownload
) -> None:
    """先 join 再读库：测试与真实服务共用同一条 sqlite 连接，而
    check_same_thread=False 只放宽线程归属断言、不提供并发安全，
    看门狗写库时主线程并发读会抛 InterfaceError。
    """
    context = _context(memory_db, tmp_path)
    job_id = _download(context, stub_download)
    assert len(stub_download.watchdogs) == 1

    stub_download.on_done.set()
    stub_download.watchdogs[0].join(5.0)

    job = context.job_store.get(job_id)
    assert job is not None
    assert job["status"] == "completed"
    assert context.cancel_events == {}, "收尾必须回收取消事件，否则 cancel_events 无界增长"


def test_sweep_interrupted_fails_crashed_download(
    memory_db: sqlite3.Connection, tmp_path: Path, stub_download: _StubDownload
) -> None:
    """崩溃重入：running 的下载任务必须被启动清扫判为失败（而不是继续显示「下载中」）。"""
    context = _context(memory_db, tmp_path)
    job_id = _download(context, stub_download)

    assert context.job_store.sweep_interrupted() == 1

    job = context.job_store.get(job_id)
    assert job is not None
    assert job["status"] == "failed"
    assert job["error"] == "服务中断"


def test_download_rejects_a_model_without_any_source(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    stub_download: _StubDownload,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没有下载源还点下载：明确拒绝并指向「导入」，而不是拼出一个坏 URL。

    清单里没有无源行，所以按替身注入一只：判据要跟着 ``ModelSpec.sources()``
    这条类型契约走，不能钉在某一行资产上。
    """
    from dramaclip.infra.model_manager.registry import ModelSpec
    from dramaclip.transport.rpc import RpcDomainError

    sourceless = ModelSpec(
        model_id="manual-only",
        kind="tts",
        engine="kokoro",
        repo_id="",
        placement="tts/manual-only",
        name="只能手工导入的模型",
    )
    monkeypatch.setattr(downloader, "spec_by_id", lambda _model_id: sourceless)
    context = _context(memory_db, tmp_path)

    with pytest.raises(RpcDomainError) as exc:
        _download(context, stub_download, "manual-only")
    assert "导入" in str(exc.value)
    assert stub_download.calls == [], "无源模型不得走到下载器"


def test_download_never_touches_the_network(
    memory_db: sqlite3.Connection, tmp_path: Path, stub_download: _StubDownload
) -> None:
    """守卫守卫本身：整条路只走替身，且带上了源与端点参数。"""
    context = _context(memory_db, tmp_path)

    _download(context, stub_download)

    assert len(stub_download.calls) == 1
    call = stub_download.calls[0]
    assert call["source"] == "auto"
    assert isinstance(call["endpoints"], dict)
    assert str(tmp_path / "models") in str(call["models_dir"])


# ---------------------------------------------------------------- P3：编排闸与结局收尾


def test_second_download_is_rejected_while_one_is_active(
    memory_db: sqlite3.Connection, tmp_path: Path, stub_download: _StubDownload
) -> None:
    """串行队列（默认 1）：多件大模型同时下会互相抢带宽，ETA 全部失真。"""
    from dramaclip.transport.rpc import RpcDomainError

    context = _context(memory_db, tmp_path)
    _download(context, stub_download)

    with pytest.raises(RpcDomainError, match="已有下载任务进行中"):
        _download(context, stub_download, "faster-whisper-small")
    assert len(stub_download.calls) == 1, "被闸住的那件不许起下载线程"


def test_disk_budget_blocks_before_starting(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    stub_download: _StubDownload,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """下载中途爆盘留下的是半成品和难懂的 OSError——预算在起线程之前拦。"""
    from types import SimpleNamespace

    from dramaclip.transport.rpc import RpcDomainError

    context = _context(memory_db, tmp_path)
    monkeypatch.setattr(
        models_api.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=10 * 1024 * 1024, total=0, used=0),
    )
    with pytest.raises(RpcDomainError, match="磁盘空间不足"):
        _download(context, stub_download)
    assert stub_download.calls == []

    # 余量充足：同一只替身正常放行（1.25 倍余量后仍够）
    monkeypatch.setattr(
        models_api.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=10 * 1024**3, total=0, used=0),
    )
    job_id = _download(context, stub_download)
    assert context.job_store.get(job_id) is not None


class _OutcomeDownload:
    """下载替身：按给定结局回报 on_result 后立即置位 on_done。"""

    def __init__(self, status: str, message: str) -> None:
        self.status, self.message = status, message

    def __call__(
        self,
        spec: object,
        models_dir: Path,
        notifier: Notifier,
        cancel: threading.Event,
        on_done: threading.Event,
        **kwargs: object,
    ) -> None:
        on_result = kwargs.get("on_result")
        assert callable(on_result), "api 必须挂 on_result，否则失败会被收成 completed"
        on_result(self.status, self.message)
        on_done.set()


def _download_and_join(context: SimpleNamespace, model_id: str = _MODEL_ID) -> str:
    before = {t.name for t in threading.enumerate()}
    job_id = str(models_api.download(context, {"model_id": model_id})["job_id"])
    for thread in threading.enumerate():
        if thread.name not in before and thread.name.startswith("dl-watch-"):
            thread.join(5.0)
    return job_id


def test_watchdog_marks_failed_with_classified_reason(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """失败必须收成 failed 并带上分类后的原因——队列页不许对坏下载报「已完成」。"""
    reason = "网络超时或连接被断——稍后重试，或在下载气泡里换个源"
    monkeypatch.setattr(downloader, "download_in_background", _OutcomeDownload("failed", reason))
    context = _context(memory_db, tmp_path)

    job_id = _download_and_join(context)

    job = context.job_store.get(job_id)
    assert job is not None
    assert job["status"] == "failed"
    assert job["error"] == reason
    assert context.cancel_events == {}, "失败收尾也要回收取消事件"


def test_watchdog_marks_cancelled(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        downloader, "download_in_background", _OutcomeDownload("cancelled", "已取消")
    )
    context = _context(memory_db, tmp_path)

    job_id = _download_and_join(context)

    job = context.job_store.get(job_id)
    assert job is not None
    assert job["status"] == "cancelled"
