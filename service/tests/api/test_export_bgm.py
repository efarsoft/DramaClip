"""BGM 床选曲门禁（export._pick_bgm_track）：设置/曲库/文件三层关，任一层不过＝现状出片。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from dramaclip.api import export as export_api
from dramaclip.engines.narration.models import PlanData, TimelineSegment
from dramaclip.infra.storage.repos import bgm as bgm_repo
from dramaclip.transport.notify import Notifier


def _context(memory_db: sqlite3.Connection, tmp_path: Path, **settings: str) -> SimpleNamespace:
    sent: list[dict[str, Any]] = []
    return SimpleNamespace(
        conn=memory_db,
        settings={"export.bgm": "1", **settings},
        notifier=Notifier(sent.append),
        sent=sent,
    )


def _plan(mode: str = "full_narration") -> PlanData:
    return PlanData(
        mode=mode,
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=0.0, end=8.0, audio="narration",
                subtitle_text="她攥紧了指节", emotion_label="suspense",  # type: ignore[arg-type]
            )
        ],
    )


def _seed_track(memory_db: sqlite3.Connection, tmp_path: Path, *, present: bool = True) -> Path:
    track = tmp_path / "bgm" / "suspense_a.mp3"
    if present:
        track.parent.mkdir(parents=True, exist_ok=True)
        track.write_bytes(b"fake-audio")
    bgm_repo.upsert_track(
        memory_db, file_path=str(track), emotion="suspense",
        duration_s=120.0, bpm=110.0,
    )
    return track


def test_pick_returns_track_and_emits_notice(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    context = _context(memory_db, tmp_path)
    track = _seed_track(memory_db, tmp_path)
    assert export_api._pick_bgm_track(context, _plan()) == track
    assert any("BGM 床" in str(m["params"]["message"]) for m in context.sent)


def test_pick_none_when_setting_off(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    context = _context(memory_db, tmp_path, **{"export.bgm": "0"})
    _seed_track(memory_db, tmp_path)
    assert export_api._pick_bgm_track(context, _plan()) is None


def test_pick_none_when_mode_excluded(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    """raw_clip/dialogue_narration 源片自带 BGM：selector 的模式门禁说了算。"""
    context = _context(memory_db, tmp_path)
    _seed_track(memory_db, tmp_path)
    assert export_api._pick_bgm_track(context, _plan(mode="raw_clip")) is None


def test_pick_none_when_library_empty(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    context = _context(memory_db, tmp_path)
    assert export_api._pick_bgm_track(context, _plan()) is None


def test_pick_none_and_degraded_when_file_missing(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """曲目登记还在、文件被删：不猜，留痕跳过（提示重扫素材库）。"""
    context = _context(memory_db, tmp_path)
    _seed_track(memory_db, tmp_path, present=False)
    assert export_api._pick_bgm_track(context, _plan()) is None
    assert any("BGM 曲目文件缺失" in str(m["params"]["message"]) for m in context.sent)
