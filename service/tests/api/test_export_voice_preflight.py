"""出片受理的配音可行性判定：能自动提取就放行，真不行才拒并说清原因。

新语义（2026-09-30）：克隆引擎 + 未配参考音色时，**自动从剧集提取**——
分析数据里「谁在什么时候说了什么」都有，音色从哪来不该问用户。只有
自动提取也不可行（无带说话人的分析、主角无 4 秒以上连续台词）才拒。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

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
