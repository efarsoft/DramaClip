"""api/models.verify 与 models.list 的资产列下发面。

前端「引擎中心」定稿（docs/design/engines-ui-options-2026-09-19.html 方案 D）要靠两列
说话：①「引擎已接入」——清单 15 项里只有 7 项（4 个引擎）真接进了工厂，不区分就是让业主拿
储备资产当可用能力；②「体检」——目录/必需文件/提交号/清单/残留/唯一路径六项，
一项 fail 就不许显示成可用。本文件钉住这两项从 RPC 出去的形状，下载器全程打桩不触网。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from dramaclip.api import models as models_api
from dramaclip.infra import config
from dramaclip.infra.model_manager import registry
from dramaclip.transport.rpc import RpcDomainError

_SENSEVOICE = "sensevoice-small"


class _RecordingNotifier:
    def __init__(self) -> None:
        self.events: list[str] = []

    def sizes_ready(self) -> None:
        self.events.append("sizes_ready")


def _context(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        data_dir=tmp_path, settings=dict(config.DEFAULTS), notifier=_RecordingNotifier()
    )


def _install_sensevoice(models_dir: Path) -> None:
    spec = next(s for s in registry.builtin_specs() if s.model_id == _SENSEVOICE)
    base = models_dir / spec.placement
    base.mkdir(parents=True, exist_ok=True)
    (base / "model.pt").write_bytes(b"\x00" * 64)


def test_verify_reports_one_model_by_id(tmp_path: Path) -> None:
    context = _context(tmp_path)
    _install_sensevoice(context.data_dir / "models")

    reports = models_api.verify(context, {"model_id": _SENSEVOICE})

    assert [r["model_id"] for r in reports] == [_SENSEVOICE]
    report = reports[0]
    assert report["ok"] is True
    assert report["engine_ready"] is True
    assert [c["name"] for c in report["checks"]][0] == "目录存在"
    assert {c["status"] for c in report["checks"]} <= {"pass", "warn"}


def test_verify_accepts_a_missing_model_as_failed_report(tmp_path: Path) -> None:
    """未安装不是 RPC 错误——体检页要显示「缺什么」，不是弹异常。"""
    context = _context(tmp_path)

    reports = models_api.verify(context, {"model_id": _SENSEVOICE})

    assert reports[0]["ok"] is False
    assert reports[0]["checks"][0] == {
        "name": "目录存在",
        "status": "fail",
        "detail": reports[0]["checks"][0]["detail"],
    }


def test_verify_without_id_covers_installed_only(tmp_path: Path) -> None:
    """总览页一次拉全部体检：未安装项逐个报「目录不存在」是噪声，只回已落盘的。"""
    context = _context(tmp_path)
    _install_sensevoice(context.data_dir / "models")

    reports = models_api.verify(context, {})

    # 云端引擎（已接线、无本地资产）也在总览体检里如实报 ok
    assert [r["model_id"] for r in reports] == [
        _SENSEVOICE,
        "dashscope-cloud-asr",
        "cosyvoice-cloud",
    ]


def test_verify_rejects_unknown_model_id(tmp_path: Path) -> None:
    context = _context(tmp_path)

    with pytest.raises(RpcDomainError, match="未知模型"):
        models_api.verify(context, {"model_id": "no-such-model"})


def test_list_models_exposes_engine_ready(tmp_path: Path) -> None:
    """引擎接入位必须随清单下发：前端的「可用 / 储备」分段全靠它。"""
    context = _context(tmp_path)

    items = models_api.list_models(context)

    flags = {item["model_id"]: item["engine_ready"] for item in items}
    assert flags["kokoro-82m"] is True
    assert flags["faster-whisper-base"] is True
    assert "sherpa-melo-zh" not in flags, "撤下的引擎还在清单里 = 资产库上一行永远装不上的死资产"
    assert flags["paraformer-large"] is True, "已接入 funasr 同栈（ParaformerEngine）"
    assert "vibevoice-1.5b" not in flags, (
        "已移除的引擎（官方运行时被上游删除）不许回潮进清单 = 资产库死资产"
    )
    assert "firedred-asr-aed-l" not in flags, (
        "已移除的引擎（官方无 pip 包/无时间戳）不许回潮进清单 = 资产库死资产"
    )
    assert all(isinstance(v, bool) for v in flags.values())


def test_list_sizes_async_fill_and_notify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """列表页体积异步化：首拉立返（None）→ 后台补算 → sizes_ready → 重拉有值且不再触发。

    12 秒级的全库磁盘统计曾把引擎中心首屏整个押住（真机 2026-10-19）——体积必须
    走后台，通知恰好一次（多了是通知风暴，少了体积永远出不来）。
    """
    registry._SIZE_CACHE.clear()
    context = _context(tmp_path)
    _install_sensevoice(context.data_dir / "models")

    def _sync_prefetch(models_dir, on_done=None):
        registry.fill_size_cache(models_dir)
        if on_done is not None:
            on_done()

    monkeypatch.setattr(registry, "prefetch_sizes", _sync_prefetch)

    first = models_api.list_models(context)
    row = next(item for item in first if item["model_id"] == _SENSEVOICE)
    assert row["size_bytes"] is None, "首拉不等磁盘统计（None=统计中）"
    assert context.notifier.events == ["sizes_ready"]

    second = models_api.list_models(context)
    row2 = next(item for item in second if item["model_id"] == _SENSEVOICE)
    assert row2["size_bytes"] == 64
    assert context.notifier.events == ["sizes_ready"], "补齐后再拉不得再次补算/通知（防风暴）"
