"""修复动作 RPC：clean_residue / orphan_list / clean_orphan / download force（§10.2 三条纪律）。

「清理残留」与体检「中断残留」判据同一条，清完再校验不许还是红；「删除多余副本」白名单制，
只删体检/orphan_list 列出的路径，名单外一律拒绝（否则等于给整个磁盘开 rmtree 的洞）；
force 重下 = 真删真下，先按 models.delete 口径清掉现有资产再起下载，不带 force「已安装」照旧
硬拒。下载器全程打桩，本文件不触网。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from dramaclip.api import models as models_api
from dramaclip.infra import jobs as jobs_mod
from dramaclip.infra.model_manager import downloader, registry
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import RpcDomainError

_WHISPER_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
_REV = "d" * 40


class _Recorder:
    """收通知的替身：log 与 model_download 都进列表，供断言播报内容。"""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def __call__(self, payload: dict) -> None:
        params = payload.get("params", {})
        text = str(params.get("message") or params.get("status") or "")
        self.messages.append(text)


def _context(memory_db: sqlite3.Connection, tmp_path: Path) -> SimpleNamespace:
    recorder = _Recorder()
    return SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        settings={},
        job_store=jobs_mod.JobStore(memory_db),
        cancel_events={},
        notifier=Notifier(recorder),
        recorder=recorder,
    )


def _spec(model_id: str) -> registry.ModelSpec:
    return next(s for s in registry.builtin_specs() if s.model_id == model_id)


def _whisper_cache(base: Path, model: str, *, rev: str = _REV) -> Path:
    cache = base / f"models--Systran--faster-whisper-{model}"
    snapshot = cache / "snapshots" / rev
    snapshot.mkdir(parents=True)
    for name in _WHISPER_FILES:
        (snapshot / name).write_bytes(b"x" * 64)
    return cache


def _installed_whisper(tmp_path: Path, model: str = "small") -> Path:
    base = tmp_path / "models" / "asr/faster-whisper"
    base.mkdir(parents=True)
    return _whisper_cache(base, model)


# ---------------------------------------------------------------- clean_residue


def test_clean_residue_removes_only_the_models_own_leftovers(tmp_path: Path) -> None:
    """同 placement 的邻居档位一字节不动：whisper 四档共用目录，范围必须按缓存根切分。"""
    cache = _installed_whisper(tmp_path, "small")
    (cache / "blobs").mkdir()
    (cache / "blobs" / ("a" * 64 + ".incomplete")).write_bytes(bytes(2048))
    (cache / "blobs" / ("b" * 64 + ".incomplete")).write_bytes(bytes(1024))
    neighbor = _whisper_cache(tmp_path / "models" / "asr/faster-whisper", "medium")
    (neighbor / "blobs").mkdir()
    (neighbor / "blobs" / ("c" * 64 + ".incomplete")).write_bytes(bytes(512))

    context = _context(None, tmp_path)  # type: ignore[arg-type]
    result = models_api.clean_residue(context, {"model_id": "faster-whisper-small"})

    assert result == {"removed": 2, "freed_bytes": 3072}
    assert not list(cache.rglob("*.incomplete"))
    assert len(list(neighbor.rglob("*.incomplete"))) == 1, "邻居档位的残留不许被顺手删掉"
    # 清完再校验不许还是红：用体检同款判据复验
    report = registry.verify(tmp_path / "models", _spec("faster-whisper-small"))
    assert next(c for c in report["checks"] if c["name"] == "中断残留")["status"] == "pass"


def test_clean_residue_nothing_to_do_is_honest_zero(tmp_path: Path) -> None:
    _installed_whisper(tmp_path)
    context = _context(None, tmp_path)  # type: ignore[arg-type]
    result = models_api.clean_residue(context, {"model_id": "faster-whisper-small"})
    assert result == {"removed": 0, "freed_bytes": 0}


def test_clean_residue_rejects_unknown_model(tmp_path: Path) -> None:
    with pytest.raises(RpcDomainError) as exc:
        models_api.clean_residue(_context(None, tmp_path), {"model_id": "no-such"})  # type: ignore[arg-type]
    assert exc.value.code == -32010


# ---------------------------------------------------------------- 多余副本


def test_orphan_list_reports_size_and_clean_orphan_deletes(tmp_path: Path) -> None:
    """§10.0 第 5 条那个 1.43GB：登记路径之外的同名缓存要能看见（含体积）、能删掉。"""
    _installed_whisper(tmp_path, "small")
    orphan = tmp_path / "models" / "models--Systran--faster-whisper-small"
    (orphan / "snapshots" / ("e" * 40)).mkdir(parents=True)
    (orphan / "snapshots" / ("e" * 40) / "model.bin").write_bytes(bytes(4096))
    context = _context(None, tmp_path)  # type: ignore[arg-type]

    listing = models_api.orphan_list(context, {"model_id": "faster-whisper-small"})
    assert listing == [{"path": str(orphan), "size_bytes": 4096}]

    result = models_api.clean_orphan(
        context, {"model_id": "faster-whisper-small", "path": str(orphan)}
    )
    assert result["ok"] is True
    assert result["freed_bytes"] == 4096
    assert not orphan.exists()
    # 登记路径那份安然无恙
    kept = tmp_path / "models" / "asr/faster-whisper" / "models--Systran--faster-whisper-small"
    assert kept.is_dir()


def test_clean_orphan_refuses_paths_outside_the_whitelist(tmp_path: Path) -> None:
    """白名单制：不在 orphan_copies 名单里的路径（哪怕是业主随手贴的合法目录）一律拒绝。"""
    _installed_whisper(tmp_path, "small")
    innocent = tmp_path / "my-own-dir"
    innocent.mkdir()
    context = _context(None, tmp_path)  # type: ignore[arg-type]

    for bad in (str(innocent), str(tmp_path), "", "relative/path"):
        with pytest.raises(RpcDomainError, match="拒绝删除"):
            models_api.clean_orphan(
                context, {"model_id": "faster-whisper-small", "path": bad}
            )
    assert innocent.is_dir()


# ---------------------------------------------------------------- force 重下


class _StubDownload:
    """下载替身：立即置位 on_done，让看门狗当场收尾（触发落盘自动体检）。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, spec, models_dir, notifier, cancel, on_done, **kwargs) -> None:  # noqa: ANN001, ANN204
        self.calls.append({"spec": spec, **kwargs})
        on_done.set()


@pytest.fixture
def stub_download(monkeypatch: pytest.MonkeyPatch) -> _StubDownload:
    stub = _StubDownload()
    monkeypatch.setattr(downloader, "download_in_background", stub)
    return stub


def _join_watchdog(model_id: str) -> None:
    for thread in threading.enumerate():
        if thread.name == f"dl-watch-{model_id}":
            thread.join(5.0)


def test_download_without_force_still_rejects_installed(
    memory_db: sqlite3.Connection, tmp_path: Path, stub_download: _StubDownload
) -> None:
    _installed_whisper(tmp_path)
    context = _context(memory_db, tmp_path)
    with pytest.raises(RpcDomainError, match="强制重新下载"):
        models_api.download(context, {"model_id": "faster-whisper-small"})  # type: ignore[arg-type]
    assert stub_download.calls == []


def test_download_force_deletes_then_redownloads_and_auto_verifies(
    memory_db: sqlite3.Connection, tmp_path: Path, stub_download: _StubDownload
) -> None:
    """force = 真删真下：旧资产按 models.delete 口径清掉，收尾时自动体检播报结论。"""
    cache = _installed_whisper(tmp_path)
    context = _context(memory_db, tmp_path)

    result = models_api.download(context, {"model_id": "faster-whisper-small", "force": True})  # type: ignore[arg-type]
    _join_watchdog("faster-whisper-small")

    assert not cache.exists()
    assert len(stub_download.calls) == 1
    job = context.job_store.get(str(result["job_id"]))
    assert job is not None and job["status"] == "completed"
    # 删光了再体检必然不过——播报必须如实说「未通过」，不许粉饰成下载成功
    assert any("自动体检未通过" in text for text in context.recorder.messages)
    assert any("强制重新下载" in text for text in context.recorder.messages)


def test_download_auto_verify_passes_for_a_healthy_landing(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """下载「落盘」出合规资产时，自动体检要报通过——绿灯必须来自判据，不是来自完成事件。"""

    def fake_download(spec, models_dir, notifier, cancel, on_done, **kwargs) -> None:  # noqa: ANN001, ANN204
        base = Path(models_dir) / spec.placement
        cache = _whisper_cache(base, "small")  # 合规形态：提交号快照四件套
        assert cache.is_dir()
        on_done.set()

    monkeypatch.setattr(downloader, "download_in_background", fake_download)
    context = _context(memory_db, tmp_path)

    models_api.download(context, {"model_id": "faster-whisper-small"})  # type: ignore[arg-type]
    _join_watchdog("faster-whisper-small")

    assert any("自动体检通过" in text for text in context.recorder.messages)
