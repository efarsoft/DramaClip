"""llama.cpp 资产一键下载：变体解析 / 双源下载校验 / 解压扁平化 / 作业接线。"""

import hashlib
import io
import json
import sqlite3
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import models as models_api
from dramaclip.infra import gpu
from dramaclip.infra.model_manager import llama_assets
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import Router, RpcRequest


def _zip_bytes(tag: str) -> bytes:
    """构造 llama.zip 替身（一层仓库前缀，llama-server.exe 在二层）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"llama-{tag}/readme.txt", tag.encode())
        zf.writestr(f"llama-{tag}/llama-server.exe", b"MZ fake server")
    return buf.getvalue()


@pytest.fixture
def no_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gpu, "snapshot_sync",
        lambda: {"ready": True, "vendor": "none", "adapters": []},
    )


def test_variant_for_follows_vendor() -> None:
    assert llama_assets.variant_for([{"vendor": "nvidia"}]) == "cuda124"
    assert llama_assets.variant_for([{"vendor": "intel"}]) == "cpu"
    assert llama_assets.variant_for([]) == "cpu"
    assert llama_assets.variant_for(None) == "cpu"


def test_install_downloads_flattens_and_marks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_gpu: None
) -> None:
    """CPU 变体一包：第一源（gh-proxy）命中 → sha256 校验 → 解压扁平化（server 落根）→ 写标记。"""
    payload = _zip_bytes("cpu")
    sha = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(llama_assets, "_CPU_ZIPS", (("llama-cpu.zip", len(payload), sha),))
    urls: list[str] = []

    def fake_download(url: str, dest: Path, size: int, **_: Any) -> None:
        urls.append(url)
        dest.write_bytes(payload)

    monkeypatch.setattr(llama_assets, "download_file", fake_download)

    result = llama_assets.install(tmp_path, cancel=threading.Event())

    assert result["variant"] == "cpu" and result["tag"] == llama_assets.LLAMA_TAG
    assert llama_assets.installed(tmp_path), "llama-server.exe 必须扁平落在工具目录根"
    assert urls[0].startswith("https://gh-proxy.com/"), "第一源是 gh-proxy"
    marker = json.loads(
        (tmp_path / "tools" / "llama.cpp" / "llama.cpp.asset.json").read_text(encoding="utf-8")
    )
    assert marker["variant"] == "cpu" and "llama-server.exe" in marker["files"]


def test_install_raises_when_sha_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_gpu: None
) -> None:
    """内容哈希对不上 → 双源全拒（资产表钉的 sha 是防篡改底线；sha 校验本体在 fetch 层）。"""

    def fake_download(url: str, dest: Path, size: int, **_: Any) -> None:
        raise OSError("SHA256 校验失败：期望 a…，实际 b…（半成品已删，重试将整文件重下）")

    monkeypatch.setattr(llama_assets, "download_file", fake_download)
    with pytest.raises(RuntimeError, match="全部源下载失败.*SHA256"):
        llama_assets.install(tmp_path, cancel=threading.Event())
    assert not llama_assets.installed(tmp_path)


def test_rpc_llama_status_and_install(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RPC 接线：status 读安装态；install 起作业至 completed、取消事件回收。"""
    from dramaclip.infra import jobs as jobs_mod
    from dramaclip.infra.storage import db

    conn = memory_db
    context = SimpleNamespace(
        conn=conn,
        data_dir=tmp_path,
        work_dir=tmp_path / "cache",
        settings={},
        notifier=Notifier(lambda m: None),
        cancel_events={},
        job_store=jobs_mod.JobStore(conn),
    )
    db.migrate(conn)
    router = Router()
    models_api.register(router, context)

    def rpc(method: str):
        response = router.dispatch(RpcRequest(id="t", method=method, params={}))
        assert response.error is None, response.error
        return response.result

    status = rpc("models.llama_status")
    assert status["installed"] is False and status["variant"] == ""

    monkeypatch.setattr(
        llama_assets, "install",
        lambda data_dir, cancel, on_progress: {
            "dir": str(data_dir), "variant": "cpu", "tag": llama_assets.LLAMA_TAG,
        },
    )
    result = rpc("models.llama_install")
    job_id = str(result["job_id"])
    job: dict[str, Any] | None = None
    for _ in range(200):
        job = context.job_store.get(job_id)
        assert job is not None
        if job["status"] in ("completed", "failed"):
            break
        threading.Event().wait(0.05)
    assert job is not None and job["status"] == "completed", job.get("error")
    assert context.cancel_events == {}, "终态后取消事件要回收"
    assert rpc("models.llama_status")["installed"] is False  # 替身没真落文件，作业链路走通即可


def test_rpc_llama_install_rejects_when_already_installed(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    from dramaclip.infra import jobs as jobs_mod
    from dramaclip.infra.storage import db

    db.migrate(memory_db)
    context = SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "cache",
        settings={},
        notifier=Notifier(lambda m: None),
        cancel_events={},
        job_store=jobs_mod.JobStore(memory_db),
    )
    router = Router()
    models_api.register(router, context)
    exe = tmp_path / "tools" / "llama.cpp" / "llama-server.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")

    response = router.dispatch(RpcRequest(id="t", method="models.llama_install", params={}))
    assert response.error is not None and "已就绪" in response.error.message
