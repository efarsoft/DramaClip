"""A3 透出：TTS 自检结果并入能力声明 caps（engines.selftest 的 TTS 分支）。

不新增 RPC 方法（protocol/* 禁碰且 test_contract_sync 钉方法集合），而是把 caps
并进既有 SelftestResult——schema 的 properties 是开放集，附加字段不违约。
reason 里可能带模型路径：透出前掩码 models_dir/data_dir/用户主目录。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import engines as engines_api
from dramaclip.engines.tts import factory
from dramaclip.engines.tts.base import EngineCaps
from dramaclip.infra.model_manager import selftest as selftest_mod
from dramaclip.transport.notify import Notifier


def _context(memory_db: sqlite3.Connection, tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "cache",
        settings={},
        notifier=Notifier(lambda _m: None),
    )


@pytest.fixture
def stub_run_tts(monkeypatch: pytest.MonkeyPatch) -> None:
    def _stub(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {"ok": True, "engine": "kokoro", "duration_s": 1.0}

    monkeypatch.setattr(selftest_mod, "run_tts", _stub)


def test_tts_selftest_result_carries_caps(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_run_tts: None,
) -> None:
    class _Fake:
        def capabilities(self) -> EngineCaps:
            return EngineCaps(
                sample_rate=24000, speed_control="native", available=True, reason="模型就绪"
            )

    monkeypatch.setattr(factory, "create", lambda engine, models_dir=None: _Fake())
    context = _context(memory_db, tmp_path)

    result = engines_api.run(context, {"model_id": "kokoro-82m"})

    assert result["ok"] is True
    caps = result["caps"]
    assert caps["sample_rate"] == 24000
    assert caps["speed_control"] == "native"
    assert caps["supports_cloning"] is False
    assert caps["available"] is True
    assert caps["reason"] == "模型就绪"
    # 落账后账本里同样带着 caps（就绪口径的能力层那一半）
    assert engines_api.results(context)["kokoro-82m"]["caps"]["sample_rate"] == 24000


def test_caps_probe_failure_lands_in_reason_not_an_exception(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_run_tts: None,
) -> None:
    def boom(engine: str, models_dir: Path | None = None) -> Any:
        raise RuntimeError("探测炸了")

    monkeypatch.setattr(factory, "create", boom)
    result = engines_api.run(_context(memory_db, tmp_path), {"model_id": "kokoro-82m"})

    assert result["ok"] is True, "自检本体成功不因 caps 探测失败而翻车"
    assert result["caps"]["available"] is False
    assert "探测炸了" in result["caps"]["reason"]


def test_caps_reason_masks_sensitive_paths(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_run_tts: None,
) -> None:
    class _Fake:
        def capabilities(self) -> EngineCaps:
            home = str(Path.home())
            return EngineCaps(
                available=False,
                reason=f"缺模型: config.json（{tmp_path / 'models' / 'tts'}），用户目录 {home}",
            )

    monkeypatch.setattr(factory, "create", lambda engine, models_dir=None: _Fake())
    result = engines_api.run(_context(memory_db, tmp_path), {"model_id": "kokoro-82m"})

    blob = json.dumps(result, ensure_ascii=False)
    assert str(tmp_path) not in blob, "models_dir/data_dir 路径段必须掩码"
    assert str(Path.home()) not in blob, "用户主目录必须掩码"
    assert "缺模型" in result["caps"]["reason"], "掩码不吞人话"
