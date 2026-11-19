"""快照目录直传（W14 续·装测 LocalEntryNotFoundError 实锤）：本地快照存在时
绕开 hub 的 refs/main 指针解析——手动/镜像落位的布局没有指针文件，离线回退
时 hub 抛 LocalEntryNotFoundError。直传本地路径让 hub 完全不介入。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dramaclip.engines.analysis.transcriber import FasterWhisperEngine


def _snapshot_with_bin(tmp_path: Path, rev: str = "abc123") -> Path:
    snapshot = tmp_path / "models--Systran--faster-whisper-base" / "snapshots" / rev
    snapshot.mkdir(parents=True)
    (snapshot / "model.bin").write_bytes(b"weights")
    return snapshot


def test_snapshot_found_returns_local_dir(tmp_path: Path) -> None:
    """快照存在时返回其目录（后续直传 model_size_or_path）。"""
    _snapshot_with_bin(tmp_path)
    engine = FasterWhisperEngine("base", device="cpu", models_dir=tmp_path)
    found = engine._require_local_model()
    assert found is not None and found.is_dir()


def test_snapshot_missing_raises(tmp_path: Path) -> None:
    engine = FasterWhisperEngine("base", device="cpu", models_dir=tmp_path)
    with pytest.raises(ValueError, match="引擎中心"):
        engine._require_local_model()


def test_local_dir_passed_not_repo_id(tmp_path: Path) -> None:
    """本地快照在场时：_create 收到的是快照目录路径，不是 repo id——
    hub 解析（refs/main 指针）完全不介入，手动/镜像落位也能加载。"""
    captured: dict = {}

    class FakeWhisperModel:
        def __init__(self, size_or_path: str, **kwargs):
            captured["size_or_path"] = size_or_path

    _snapshot_with_bin(tmp_path)
    engine = FasterWhisperEngine("base", device="cpu", models_dir=tmp_path)
    snapshot = engine._require_local_model()
    engine._create(FakeWhisperModel, "cpu", local_dir=snapshot)
    assert captured["size_or_path"] == str(snapshot)
