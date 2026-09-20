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


def _context(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(data_dir=tmp_path, settings=dict(config.DEFAULTS))


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

    assert [r["model_id"] for r in reports] == [_SENSEVOICE]


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
    assert flags["paraformer-large"] is False, "无实现的引擎被报成可用 = 业主点了才知是空的"
    assert all(isinstance(v, bool) for v in flags.values())
