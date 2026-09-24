"""api/models 的导入面：inspect（只读体检）/ commit（作业化落位）/ records / forget。

这一段是业主定稿方案 D 的 D4 向导在服务端的四个出入口。规矩有三条，本文件逐条钉住：

1. **判据只有一份**：API 层不重复实现「能不能导入」——它把 importer 的 ValueError 原样
   翻成 RPC 领域错误/作业失败原因，所以 UI 上看到的话术与引擎侧的判据必然同源。
2. **落位是长活**：GB 级复制不能占住 RPC 线程，所以走作业；作业必须**建在 running 上**
   （与 models.download 同一处历史 bug：漏掉 mark_running，看门狗只认 running，队列页
   会留一只永不结束的「导入中」）。
3. **身份只给内置清单**：认不出身份的目录只进登记本，不进 models.list——那一列每行都能被
   「选为生效」，给它一个假身份等于绕过这条闸。

复制/移动/冲突的真文件系统行为在 tests/infra/model_manager/test_importer_commit.py 里钉；
这里只钉 RPC 形状，下载器与网络一律不碰。
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from dramaclip.api import models as models_api
from dramaclip.infra import config
from dramaclip.infra import jobs as jobs_mod
from dramaclip.infra.model_manager import importer
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import RpcDomainError

SNAPSHOT = "0123456789abcdef0123456789abcdef01234567"
CACHE_NAME = "models--Systran--faster-whisper-medium"
MODEL_ID = "faster-whisper-medium"


def _write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _cache_dir(base: Path) -> Path:
    cache = base / CACHE_NAME
    snapshot = cache / "snapshots" / SNAPSHOT
    for name in ("config.json", "tokenizer.json", "vocabulary.txt"):
        _write(snapshot / name, b"meta")
    _write(snapshot / "model.bin", b"m" * 512)
    _write(cache / "refs" / "main", SNAPSHOT.encode())
    _write(cache / "trees" / f"{SNAPSHOT}.json", b'{"files":[]}')
    return cache


@pytest.fixture(autouse=True)
def size_within_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """把标称体积钉成 512B：真复制 1.5GB 稀疏文件会变成实打实的磁盘 I/O，测的却是 RPC 形状。"""
    monkeypatch.setattr(importer, "_nominal_bytes", lambda _label: 512)


@pytest.fixture(autouse=True)
def drain_import_threads(memory_db: sqlite3.Connection) -> Iterator[None]:
    """收尾前等落位线程退场：内存库随用例关闭，看门狗再碰它就是「closed database」。

    必须显式依赖 ``memory_db``：夹具按建立的倒序拆，先建的就是后拆——不声明这个依赖，
    库会先关、线程后醒，整批用例的报告里就会刷满无害但刺眼的线程异常，下一次真回归
    就再也看不见别的问题。
    """
    yield
    for thread in threading.enumerate():
        if thread.name.startswith(("import-", "import-watch-")):
            thread.join(timeout=5.0)


def _context(memory_db: sqlite3.Connection, tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        settings=dict(config.DEFAULTS),
        job_store=jobs_mod.JobStore(memory_db),
        cancel_events={},
        notifier=Notifier(lambda _m: None),
    )


def _settle(context: SimpleNamespace, job_id: str, timeout: float = 15.0) -> dict[str, object]:
    """等作业落到终态：落位跑在后台线程里，测试不 sleep 轮询就无法断言收尾。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = context.job_store.get(job_id)
        assert job is not None
        if jobs_mod.is_terminal(str(job["status"])):
            return job
        time.sleep(0.02)
    raise AssertionError(f"作业 {job_id} 超时未收尾")


def _commit(context: SimpleNamespace, params: dict[str, object]) -> dict[str, object]:
    """提交并等到收尾：返回终态作业，用例不必每处自己处理线程时序。"""
    return _settle(context, str(models_api.import_commit(context, params)["job_id"]))


def test_import_inspect_reports_the_second_step_without_writing(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    context = _context(memory_db, tmp_path)
    source = _cache_dir(tmp_path / "下载")

    report = models_api.import_inspect(context, {"path": str(source)})

    assert report["model_id"] == MODEL_ID
    assert report["ok"] is True, report["checks"]
    assert [check["name"] for check in report["checks"]][:2] == ["目录内容", "必需文件"]
    assert not (context.data_dir / "models" / "asr").exists(), "第 ② 步是只读的"


def test_import_inspect_rejects_a_blank_or_missing_path(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """空参数与不存在的目录都是领域错误：向导要显示话术，不是弹 JSON-RPC 内部异常。"""
    context = _context(memory_db, tmp_path)

    with pytest.raises(RpcDomainError, match="path"):
        models_api.import_inspect(context, {})
    with pytest.raises(RpcDomainError, match="不存在"):
        models_api.import_inspect(context, {"path": str(tmp_path / "没这个东西")})


def test_import_commit_lands_the_asset_and_completes_the_job(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    context = _context(memory_db, tmp_path)
    source = _cache_dir(tmp_path / "下载")

    job = _commit(context, {"path": str(source), "mode": "copy"})

    assert job["status"] == "completed", job["error"]
    placed = context.data_dir / "models" / "asr" / "faster-whisper" / CACHE_NAME
    assert (placed / "snapshots" / SNAPSHOT / "model.bin").read_bytes() == b"m" * 512


def test_import_commit_creates_the_job_already_running(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """建在 pending 上的导入作业永远收不了尾：看门狗的回写条件是 status==running。"""
    context = _context(memory_db, tmp_path)
    source = _cache_dir(tmp_path / "下载")

    job_id = models_api.import_commit(context, {"path": str(source), "mode": "copy"})["job_id"]

    assert context.job_store.get(str(job_id))["status"] == jobs_mod.STATUS_RUNNING


def test_import_commit_surfaces_the_gate_as_a_failed_job(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """第 ② 步没过就不许进第 ③ 步：拒绝话术原样回给向导，库里一个字节都不许多。"""
    context = _context(memory_db, tmp_path)
    flat = tmp_path / "faster-whisper-medium"
    _write(flat / "config.json", b"meta")
    _write(flat / "model.bin", b"m" * 512)

    job = _commit(context, {"path": str(flat), "mode": "copy"})

    assert job["status"] == "failed"
    assert "体检" in str(job["error"])
    placement = context.data_dir / "models" / "asr" / "faster-whisper"
    assert not placement.exists() or list(placement.iterdir()) == []


def test_the_row_points_at_the_copy_the_engine_actually_reads(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """先仅登记、后来又复制进库：库里躺着两份，行上必须挂引擎此刻真读到的那一份。

    挂错成登记项的话，「移除」会去撤一条无关登记而留着库内那份，UI 也报错了来源。
    """
    context = _context(memory_db, tmp_path)
    source = _cache_dir(tmp_path / "下载")
    _commit(context, {"path": str(source), "mode": "register"})
    _commit(context, {"path": str(source), "mode": "copy"})

    row = next(item for item in models_api.list_models(context) if item["model_id"] == MODEL_ID)
    assert row["status"] == "installed"
    assert row["imported"]["mode"] == "copy"
    landed = context.data_dir / "models" / "asr" / "faster-whisper" / CACHE_NAME
    assert row["imported"]["path"] == str(landed)
    assert {r["mode"] for r in models_api.import_records(context)["records"]} == {
        "register",
        "copy",
    }, "另一份仍在登记本里，业主才知道库里多了一份"


def test_imported_asset_is_marked_in_the_library(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """「本地导入」与「应用下载」必须分得开：移除时提示的是「连源目录一起删」还是只删库内。"""
    context = _context(memory_db, tmp_path)
    source = _cache_dir(tmp_path / "下载")
    _commit(context, {"path": str(source), "mode": "copy"})

    landed = next(
        row for row in models_api.list_models(context) if row["status"] == "installed"
    )
    imported = landed["imported"]
    assert landed["model_id"] == MODEL_ID
    assert imported["mode"] == "copy"
    assert imported["source_path"] == str(source)
    assert imported["incomplete"] is False
    assert imported["label"] == "Whisper Medium（高准确度）"
    assert imported["imported_at"] > 0, "移除时的「何时导入」提示要有据可查"


def test_registered_only_asset_shows_as_an_external_path(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """仅登记不复制：模型还在业主自己的盘上，引擎读不到——所以它不能算「已安装」。"""
    context = _context(memory_db, tmp_path)
    source = _cache_dir(tmp_path / "下载")
    _commit(context, {"path": str(source), "mode": "register"})

    item = next(row for row in models_api.list_models(context) if row["model_id"] == MODEL_ID)
    assert item["status"] == "not_installed"
    assert item["imported"]["mode"] == "register"
    assert item["imported"]["path"] == str(source)


def test_unrecognized_directory_lands_in_the_registration_not_the_model_list(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """清单外的目录只进登记本：``models.list`` 每行都得有身份，造一行假身份等于骗过「选为生效」。

    「外部资产 · 引擎未接入」这行字仍然要在库里出现（D4 验收标准），但它的真相源是登记本，
    不是被塞进内置清单的假模型行——engine_ready 靠结构保证，而不是靠记得写 false。
    """
    context = _context(memory_db, tmp_path)
    given = tmp_path / "同事给的模型"
    _write(given / "whatever.safetensors", b"s" * 512)
    _commit(
        context,
        {"path": str(given), "mode": "register", "external_kind": "tts", "label": "同事的音色"},
    )
    source = _cache_dir(tmp_path / "另一个下载")
    _commit(context, {"path": str(source), "mode": "register"})

    rows = models_api.list_models(context)
    assert all(row["model_id"] for row in rows), "内置清单里的每一行都必须有身份"
    assert "同事的音色" not in {row["name"] for row in rows}

    records = models_api.import_records(context)["records"]
    assert {record["model_id"] for record in records} == {MODEL_ID, None}, "认得出的也要在登记本里"
    external = next(record for record in records if record["model_id"] is None)
    assert external["kind"] == "tts"
    assert external["label"] == "同事的音色"
    assert external["path"] == str(given)
    assert external["engine"] == "", "认不出身份就没有承接引擎，UI 据此报「引擎未接入」"


def test_import_records_survive_a_corrupt_manifest_without_hiding_it(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    context = _context(memory_db, tmp_path)
    models_dir = context.data_dir / "models"
    models_dir.mkdir(parents=True)
    importer.manifest_path(models_dir).write_text("{不是 json", encoding="utf-8")

    result = models_api.import_records(context)

    assert result["records"] == []
    assert result["error"] != "", "读不出来必须说出来，否则「本地导入」标记会凭空消失"


def test_import_forget_drops_the_record_and_keeps_the_owners_files(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """撤销登记只动登记本：业主原目录里的字节只能由他自己处置。"""
    context = _context(memory_db, tmp_path)
    source = _cache_dir(tmp_path / "下载")
    _commit(context, {"path": str(source), "mode": "register"})

    models_api.import_forget(context, {"path": str(source)})

    assert importer.records(context.data_dir / "models") == []
    assert source.is_dir()
    row = next(item for item in models_api.list_models(context) if item["model_id"] == MODEL_ID)
    assert row["imported"] is None, "撤销之后这一行得回到「不是导入来的」"


def test_import_forget_refuses_a_path_inside_the_library(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """库内那份是真资产：只撤登记就变成「躺在库里但没人知道」——那种情况必须走 models.delete。"""
    context = _context(memory_db, tmp_path)
    source = _cache_dir(tmp_path / "下载")
    _commit(context, {"path": str(source), "mode": "copy"})
    landed = importer.records(context.data_dir / "models")[0]["path"]

    with pytest.raises(RpcDomainError, match="库内"):
        models_api.import_forget(context, {"path": str(landed)})

    assert importer.records(context.data_dir / "models") != [], "拒绝要写在改登记本之前"
    assert Path(str(landed)).is_dir()


def test_import_forget_rejects_a_blank_or_unregistered_path(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """空 path 是参数错；查无此登记也要报错，否则 UI 会对一个拼错的路径显示成功。"""
    context = _context(memory_db, tmp_path)

    with pytest.raises(RpcDomainError, match="path"):
        models_api.import_forget(context, {})
    with pytest.raises(RpcDomainError, match="登记"):
        models_api.import_forget(context, {"path": str(tmp_path / "没这条")})


def test_delete_of_a_registered_only_asset_only_forgets_the_record(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """业主原来的字节只能由他自己处置：撤销登记不 rmtree 别人的目录。"""
    context = _context(memory_db, tmp_path)
    source = _cache_dir(tmp_path / "下载")
    _commit(context, {"path": str(source), "mode": "register"})

    models_api.delete(context, {"model_id": MODEL_ID})

    assert source.is_dir()
    assert importer.records(context.data_dir / "models") == []


def test_delete_removes_a_landed_copy_and_its_record(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    context = _context(memory_db, tmp_path)
    source = _cache_dir(tmp_path / "下载")
    _commit(context, {"path": str(source), "mode": "copy"})

    models_api.delete(context, {"model_id": MODEL_ID})

    assert not (context.data_dir / "models" / "asr" / "faster-whisper" / CACHE_NAME).exists()
    assert importer.records(context.data_dir / "models") == []
    assert source.is_dir(), "删除库内副本不动业主的源目录"


def test_import_commit_refuses_a_source_inside_the_library(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """库里那份当来源 = 把自己拷给自己，覆盖时还会把原件一起改名：直接拒绝。"""
    context = _context(memory_db, tmp_path)
    library = context.data_dir / "models" / "asr" / "faster-whisper"
    source = _cache_dir(library)

    job = _commit(context, {"path": str(source), "mode": "copy"})

    assert job["status"] == "failed"
    assert "模型目录内" in str(job["error"])
    assert source.is_dir() and source.name == CACHE_NAME, "拒绝不该动源目录一根手指"


def test_import_commit_rejects_a_blank_path(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    """空 path 连作业都不该建：作业列表里留一只注定失败的记录是噪声。"""
    context = _context(memory_db, tmp_path)

    with pytest.raises(RpcDomainError, match="path"):
        models_api.import_commit(context, {"mode": "copy"})

    assert context.job_store.list_recent() == []
