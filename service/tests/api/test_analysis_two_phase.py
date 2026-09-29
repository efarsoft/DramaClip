"""分析两段写入：第一层（转写/场景/音频/OCR）先落库、语义层完成才标 done。

钉三件事：①语义层挂 → 转写结果已落库（语义列空）、集标 failed——最贵的转写
不被最易挂的 LLM 连坐；②同签名重入 → 转写器不再被调、只补语义并标 done；
③签名不同 / 第一层产物损坏 → 全量重算，绝不沿用不属于这份源的旧转写。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from dramaclip.api import analysis as analysis_api
from dramaclip.engines.analysis.models import AsrSegment, AudioFeatures
from dramaclip.engines.analysis.pipeline import EpisodeRawAnalysis
from dramaclip.engines.semantic.models import SemanticResult
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.notify import Notifier

_SIG = "sig-1"


def _context(memory_db: sqlite3.Connection, tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "work",
        settings={"analysis.ocr_enabled": "0"},
        analysis_runtime=SimpleNamespace(transcriber=lambda: SimpleNamespace(name="fake")),
        job_store=SimpleNamespace(set_progress=lambda *a, **k: None),
        notifier=Notifier(lambda _m: None),
    )


def _episode(memory_db: sqlite3.Connection, tmp_path: Path) -> dict:
    project = projects_repo.create(memory_db, "剧", str(tmp_path))
    episodes_repo.replace_all(
        memory_db,
        str(project["id"]),
        [{"episode_number": 1, "source_path": str(tmp_path / "ep1.mp4"), "duration": 60.0}],
    )
    return episodes_repo.list_by_project(memory_db, str(project["id"]))[0]


def _has_text(record: dict, text: str) -> bool:
    segments = json.loads(record["asr_segments"])
    return any(text in str(item.get("text", "")) for item in segments)


def _raw() -> EpisodeRawAnalysis:
    return EpisodeRawAnalysis(
        asr_segments=[AsrSegment(start=0.0, end=1.0, text="台词", words=[])],
        scenes=[],
        audio=AudioFeatures(),
    )


def _run_analyze(
    monkeypatch: pytest.MonkeyPatch,
    context: SimpleNamespace,
    episode: dict,
    *,
    enhance_fails: bool,
) -> tuple[bool, dict[str, int]]:
    calls = {"pipeline": 0, "enhance": 0}

    def fake_pipeline(**_kwargs: object) -> EpisodeRawAnalysis:
        calls["pipeline"] += 1
        return _raw()

    def fake_enhance(_raw: EpisodeRawAnalysis, _settings: object, **_kw: object) -> SemanticResult:
        calls["enhance"] += 1
        if enhance_fails:
            raise RuntimeError("LLM 403")
        return SemanticResult()

    monkeypatch.setattr(analysis_api.pipeline, "analyze_episode", fake_pipeline)
    monkeypatch.setattr(analysis_api.semantic_pipeline, "enhance", fake_enhance)
    monkeypatch.setattr(analysis_api, "_current_signature", lambda _ctx, _ep: _SIG)
    ok = analysis_api._analyze_one(
        context, "job1", episode, 0, 1, "zh", threading.Event()
    )
    return ok, calls


def test_semantic_failure_keeps_transcription(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(memory_db, tmp_path)
    episode = _episode(memory_db, tmp_path)

    ok, _calls = _run_analyze(monkeypatch, context, episode, enhance_fails=True)

    assert ok is False
    record = analysis_repo.get(memory_db, str(episode["id"]))
    assert record is not None and _has_text(record, "台词"), "转写结果必须已落库"
    assert not record["conflict_scores"], "语义列必须为空（重入判据的依据）"
    assert episodes_repo.get(memory_db, str(episode["id"]))["status"] == "failed"


def test_retry_same_signature_skips_transcription(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(memory_db, tmp_path)
    episode = _episode(memory_db, tmp_path)

    _run_analyze(monkeypatch, context, episode, enhance_fails=True)
    episode = episodes_repo.get(memory_db, str(episode["id"]))
    ok, calls = _run_analyze(monkeypatch, context, episode, enhance_fails=False)

    assert ok is True
    assert calls["pipeline"] == 0, "同签名重入不许重跑转写"
    assert calls["enhance"] == 1
    record = analysis_repo.get(memory_db, str(episode["id"]))
    assert record["conflict_scores"] is not None
    assert episodes_repo.get(memory_db, str(episode["id"]))["status"] == "done"


def test_signature_mismatch_redoes_everything(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(memory_db, tmp_path)
    episode = _episode(memory_db, tmp_path)
    analysis_repo.upsert(
        context.conn,
        str(episode["id"]),
        asr_segments='[{"start":0,"end":1,"text":"旧源台词","words":[]}]',
        scene_data="[]",
        audio_features="{}",
        conflict_scores="[]",
        highlights="[]",
        genre="",
    )
    episodes_repo.set_source_signature(memory_db, str(episode["id"]), "old-source")

    ok, calls = _run_analyze(monkeypatch, context, episode, enhance_fails=False)

    assert ok is True
    assert calls["pipeline"] == 1, "签名失配必须全量重算"
    record = analysis_repo.get(memory_db, str(episode["id"]))
    assert _has_text(record, "台词"), "新转写必须盖掉旧源产物"


def test_corrupt_first_layer_redoes_everything(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(memory_db, tmp_path)
    episode = _episode(memory_db, tmp_path)
    analysis_repo.upsert(
        context.conn,
        str(episode["id"]),
        asr_segments="not-json",
        scene_data=None,
        audio_features=None,
        conflict_scores=None,
    )

    ok, calls = _run_analyze(monkeypatch, context, episode, enhance_fails=False)

    assert ok is True
    assert calls["pipeline"] == 1, "第一层产物损坏按不可续走全量重算"
