"""api/models.relayout：存量 snapshots/main 就地迁移的 RPC 面。

守卫三条边界：迁移成功回报新路径并播报日志；解析不到提交号/非 whisper 档位时
ValueError 原文转域错误（那是给业主看的诚实结论，不许吞）；未知 model_id 走 -32010。
提交号解析全程打桩，本文件不触网。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from dramaclip.api import models as models_api
from dramaclip.infra.model_manager import downloader
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import RpcDomainError

_SHA = "c" * 40
_WHISPER_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")


def _context(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        data_dir=tmp_path,
        settings={},
        notifier=Notifier(lambda _m: None),
    )


def _legacy_cache(tmp_path: Path, model: str = "base") -> Path:
    """历史下载器留下的形态：snapshots/main 四件套、无 refs、无 trees。"""
    placement = "asr/faster-whisper"
    cache = tmp_path / "models" / placement / f"models--Systran--faster-whisper-{model}"
    snapshot = cache / "snapshots" / "main"
    snapshot.mkdir(parents=True)
    for name in _WHISPER_FILES:
        (snapshot / name).write_bytes(b"x" * 16)
    return cache


def test_relayout_migrates_and_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = _legacy_cache(tmp_path)
    monkeypatch.setattr(downloader, "resolve_revision", lambda *_a, **_k: _SHA)

    result = models_api.relayout(_context(tmp_path), {"model_id": "faster-whisper-base"})

    assert result["migrated"] is True
    assert Path(str(result["path"])) == cache / "snapshots" / _SHA
    assert (cache / "refs" / "main").read_text(encoding="utf-8") == _SHA


def test_relayout_says_the_truth_when_revision_unresolvable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _legacy_cache(tmp_path)
    monkeypatch.setattr(downloader, "resolve_revision", lambda *_a, **_k: None)

    with pytest.raises(RpcDomainError) as exc:
        models_api.relayout(_context(tmp_path), {"model_id": "faster-whisper-base"})
    assert "解析不到提交号" in str(exc.value)


def test_relayout_rejects_non_whisper_and_unknown_id(tmp_path: Path) -> None:
    context = _context(tmp_path)
    with pytest.raises(RpcDomainError, match="不是 whisper 系"):
        models_api.relayout(context, {"model_id": "kokoro-82m"})
    with pytest.raises(RpcDomainError) as exc:
        models_api.relayout(context, {"model_id": "no-such-model"})
    assert exc.value.code == -32010
