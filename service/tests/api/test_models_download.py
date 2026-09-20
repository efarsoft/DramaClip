"""api/models.download 的任务生命周期：`model_download` 必须**建在 running 上**。

钉的是 dec059d 那一处真 bug：漏掉 mark_running 时，下载成功的任务永远停在 pending，
队列页显示一只永不结束的「下载中」——看门狗只认 running 才收尾，成功路径无人回写。
（原先这里还写着"重启也清不掉"，那半句已不成立：启动清扫现已连 pending 一并复位，
见 `infra/jobs.py::sweep_interrupted`。收尾那一头仍然只认 running，本守卫照旧必要。）
下载器全程打桩，本文件不触网。
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
    """跑一次 models.download，返回 job_id（顺带登记本次起的看门狗线程）。

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

    看门狗的回写条件是 status == running；停在 pending 的下载任务它不认，下载明明成功
    也无人收尾，队列页永远显示「下载中」。（崩溃残留那一头已不再是本守卫的理由：
    启动清扫现已连 pending 一并复位，见 `infra/jobs.py::sweep_interrupted`。）
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
    """下载完成（on_done 置位）→ 看门狗收尾该 running 任务并回收取消事件。

    先 join 再读库：测试与真实服务共用同一条 sqlite 连接，而
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

    清单里如今没有无源行（原先是 sherpa-melo-zh，引擎已撤下），所以按替身注入一只：
    判据要跟着 ``ModelSpec.sources()`` 这条类型契约走，不能钉在某一行资产上。
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
