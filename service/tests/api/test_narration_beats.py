"""B9：_casting_for 把落库的 audio_features.beats 装进 EpisodeMaterial。

坏 JSON / 缺列一律降级为空 beats（不 raise）：节拍吸附是意图层增强，
装配层不为它付「这条方案出不了片」的代价。
"""

from __future__ import annotations

import json
import sqlite3

from dramaclip.api import narration as narration_api
from dramaclip.engines.analysis.models import AudioFeatures
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import projects as projects_repo


def _seed_episode(conn: sqlite3.Connection, *, audio_features: str | None) -> dict[str, object]:
    project = projects_repo.create(conn, "节拍", "D:/src-beats")
    episodes_repo.replace_all(
        conn,
        str(project["id"]),
        [{"episode_number": 1, "source_path": "D:/src-beats/ep1.mp4", "duration": 60.0}],
    )
    episode = episodes_repo.list_by_project(conn, str(project["id"]))[0]
    analysis_repo.upsert(
        conn,
        str(episode["id"]),
        asr_segments=json.dumps([{"start": 0.2, "end": 1.0, "text": "台词一"}]),
        scene_data="[]",
        audio_features=audio_features,
        conflict_scores=json.dumps(
            [{"scene_index": 0, "start": 0.0, "end": 10.0, "score": 80}]
        ),
        highlights="[]",
    )
    return episode


def _cast(conn: sqlite3.Connection, episode: dict[str, object]) -> object:
    from types import SimpleNamespace

    context = SimpleNamespace(conn=conn, notifier=SimpleNamespace(log=lambda *a: None))
    variant = narration_api._Variant(
        name="角度1", reason="理由", episode_numbers=[1], angle_block=""
    )
    _scenes, _highlights, material = narration_api._casting_for(
        context, [episode], variant  # type: ignore[arg-type]
    )
    return material[str(episode["id"])]


def test_beats_from_audio_features_column_land_in_episode_material(
    memory_db: sqlite3.Connection,
) -> None:
    """分析产物里的 beats 必须一路带到编排层：断在这条链上，B9 就只是落库的死数据。"""
    episode = _seed_episode(
        memory_db,
        audio_features=AudioFeatures(beats=[1.0, 1.5, 2.0]).model_dump_json(),
    )
    material = _cast(memory_db, episode)
    assert tuple(material.beats) == (1.0, 1.5, 2.0)  # type: ignore[attr-defined]
    assert [seg.text for seg in material.asr] == ["台词一"]  # type: ignore[attr-defined]


def test_broken_audio_features_json_degrades_to_empty_beats(
    memory_db: sqlite3.Connection,
) -> None:
    episode = _seed_episode(memory_db, audio_features="{not json")
    material = _cast(memory_db, episode)
    assert tuple(material.beats) == ()  # type: ignore[attr-defined]


def test_missing_audio_features_column_degrades_to_empty_beats(
    memory_db: sqlite3.Connection,
) -> None:
    episode = _seed_episode(memory_db, audio_features=None)
    material = _cast(memory_db, episode)
    assert tuple(material.beats) == ()  # type: ignore[attr-defined]


def test_legacy_audio_features_json_without_beats_field(
    memory_db: sqlite3.Connection,
) -> None:
    """B9 之前落库的 JSON 没有 beats 字段：旧库不重分析也照常出方案。"""
    legacy = json.dumps({"silence_ratio": 0.4, "bpm": 90.0})
    episode = _seed_episode(memory_db, audio_features=legacy)
    material = _cast(memory_db, episode)
    assert tuple(material.beats) == ()  # type: ignore[attr-defined]
