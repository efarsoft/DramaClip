"""出片受理的配音可行性判定：能自动提取就放行，真不行才拒并说清原因。

新语义（2026-09-30）：克隆引擎 + 未配参考音色时，**自动从剧集提取**——
分析数据里「谁在什么时候说了什么」都有，音色从哪来不该问用户。只有
自动提取也不可行（无带说话人的分析、主角无 4 秒以上连续台词）才拒。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import export as export_api
from dramaclip.engines.narration.models import PlanData, TimelineSegment
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo


def _settings(engine: str, voice: str = "") -> dict[str, str]:
    return {
        "tts.engine": engine,
        f"tts.voice.{engine}": voice,
        "export.encoder": "libx264",
    }


def _seed(memory_db: sqlite3.Connection, tmp_path: Path) -> tuple[str, str]:
    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    project_id = str(projects_repo.create(memory_db, "剧", str(tmp_path))["id"])
    episodes_repo.replace_all(
        memory_db,
        project_id,
        [{"episode_number": 1, "source_path": str(source), "duration": 120.0}],
    )
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    plan_data = PlanData(
        mode="dialogue_narration",
        timeline=[
            TimelineSegment(
                episode_id=episode_id,
                start=0.0,
                end=5.0,
                audio="narration",
                narration_id="n1",
            )
        ],
        narration_texts=[
            {"id": "n1", "text": "他花几百万两杀妻——点击左下角，免费观看全集。"}
        ],
    )
    plans_repo.create(
        memory_db,
        project_id,
        "dialogue_narration",
        [episode_id],
        plan_data.model_dump(),
        status="ready",
    )
    plan_id = str(plans_repo.list_by_project(memory_db, project_id)[0]["id"])
    return project_id, plan_id


def _context(memory_db: sqlite3.Connection, settings: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(conn=memory_db, settings=settings)


def test_clone_engine_with_usable_span_passes_preflight(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """有带说话人的分析 → 自动提取可行 → 受理放行（渲染时补音色）。"""
    project_id, plan_id = _seed(memory_db, tmp_path)

    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    analysis_repo.upsert(
        memory_db,
        episode_id,
        asr_segments='[{"start": 0, "end": 8, "text": "主角长台词", "speaker": "角色A"}]',
        scene_data="[]",
        audio_features="{}",
    )
    context = _context(memory_db, _settings("indextts2"))
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    analysis_repo.upsert(
        memory_db,
        episode_id,
        asr_segments='[{"start": 0, "end": 8, "text": "主角长台词", "speaker": "角色A"}]',
        scene_data="[]",
        audio_features="{}",
    )
    plan_data = PlanData.model_validate(plans_repo.get(memory_db, plan_id)["plan_data"])
    assert export_api._voice_issue_or_none(context, plan_data, project_id) is None, (
        "有带说话人的分析时自动提取可行，不应拦截"
    )


def test_clone_engine_without_speaker_analysis_is_rejected(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """无带说话人的分析（自动提取不可行）→ 拒绝并指引。"""
    project_id, plan_id = _seed(memory_db, tmp_path)
    context = _context(memory_db, _settings("indextts2"))
    plan_data = PlanData.model_validate(plans_repo.get(memory_db, plan_id)["plan_data"])
    issue = export_api._voice_issue_or_none(context, plan_data, project_id)
    assert issue is not None and "自动提取" in issue


def _seed_done_analysis(memory_db: sqlite3.Connection, project_id: str) -> None:
    episode = episodes_repo.list_by_project(memory_db, project_id)[0]
    episodes_repo.set_status(memory_db, str(episode["id"]), "done")
    analysis_repo.upsert(
        memory_db,
        str(episode["id"]),
        asr_segments='[{"start": 0, "end": 8, "text": "主角长台词", "speaker": "角色A"}]',
        scene_data="[]",
        audio_features="{}",
    )


def _log_only_notifier() -> SimpleNamespace:
    return SimpleNamespace(log=lambda *_args, **_kw: None)


def test_ensure_clone_voice_reuses_sibling_result(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """并发批次防互踩：兄弟任务刚写入 DB 的音色直接复用，不再重复提取。

    2026-10-06 真实事故：一批 4 条出片并发跑自动提取，同秒同名 raw 互踩
    （先洗完先删），后到的清洗报「Error opening input」整条失败。
    """
    project_id, _ = _seed(memory_db, tmp_path)
    from dramaclip.engines.tts import auto_voice
    from dramaclip.infra.storage.repos import settings as settings_repo

    _seed_done_analysis(memory_db, project_id)
    calls: list[int] = []

    def fake_extract(conn: Any, data_dir: Path, episodes: list[dict[str, Any]]) -> dict[str, Any]:
        calls.append(1)
        voice_path = str(data_dir / "voices" / "ref.wav")
        settings_repo.set_value(conn, "tts.voice.indextts2", voice_path)
        return {"path": voice_path, "speaker": "角色A", "start": 0.0, "end": 8.0, "seconds": 8.0}

    monkeypatch.setattr(auto_voice, "extract_auto_voice", fake_extract)
    context = SimpleNamespace(conn=memory_db, data_dir=tmp_path, notifier=_log_only_notifier())

    settings_first = _settings("indextts2")
    export_api._ensure_clone_voice(
        context, {}, project_id, episodes_repo, settings_first  # type: ignore[arg-type]
    )
    settings_second = _settings("indextts2")
    export_api._ensure_clone_voice(
        context, {}, project_id, episodes_repo, settings_second  # type: ignore[arg-type]
    )

    assert len(calls) == 1, "第二次调用应复用兄弟任务刚落库的音色，不重复提取"
    assert settings_second["tts.voice.indextts2"].endswith("ref.wav")


def test_ensure_clone_voice_writes_engine_specific_key(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cosyvoice 提取的音色写 tts.voice.cosyvoice，不许错写进 indextts2 的 key。"""
    project_id, _ = _seed(memory_db, tmp_path)
    from dramaclip.engines.tts import auto_voice
    from dramaclip.infra.storage.repos import settings as settings_repo

    _seed_done_analysis(memory_db, project_id)

    def fake_extract(conn: Any, data_dir: Path, episodes: list[dict[str, Any]]) -> dict[str, Any]:
        return {"path": str(data_dir / "ref.wav"), "speaker": "角色A", "seconds": 8.0}

    monkeypatch.setattr(auto_voice, "extract_auto_voice", fake_extract)
    context = SimpleNamespace(conn=memory_db, data_dir=tmp_path, notifier=_log_only_notifier())
    settings = _settings("cosyvoice")
    export_api._ensure_clone_voice(
        context, {}, project_id, episodes_repo, settings  # type: ignore[arg-type]
    )

    assert settings["tts.voice.cosyvoice"].endswith("ref.wav")
    assert settings_repo.get_all(memory_db).get("tts.voice.indextts2") in (None, ""), (
        "cosyvoice 的参考音色不得写进 indextts2 的 key"
    )
