"""narration 命名空间：generate_plans（job）/ list_plans。"""

from __future__ import annotations

import json
import threading
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.engines.narration import pipeline as narration_pipeline
from dramaclip.engines.semantic.models import ConflictScore, HighlightSegment
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.rpc import Router, RpcDomainError

_ERR_PROJECT_NOT_FOUND = -32101
_ERR_NO_ANALYSIS = -32301
_ERR_MODE_UNSUPPORTED = -32302

SUPPORTED_MODES = (
    "raw_clip",
    "intro_narration",
    "cross_narration",
    "ultra_short_hook",
    "dialogue_narration",
    "full_narration",
)


def register(router: Router, context: AppContext) -> None:
    router.register("narration.generate_plans", lambda params: generate_plans(context, params))
    router.register("narration.list_plans", lambda params: list_plans(context, params))


def generate_plans(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    project_id = str(params.get("project_id", ""))
    if projects_repo.get(context.conn, project_id) is None:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
    modes = [str(mode) for mode in params.get("modes", [])]
    invalid = [mode for mode in modes if mode not in SUPPORTED_MODES]
    if invalid:
        raise RpcDomainError(_ERR_MODE_UNSUPPORTED, f"模式暂未支持: {', '.join(invalid)}")
    done_episodes = [
        episode
        for episode in episodes_repo.list_by_project(context.conn, project_id)
        if episode["status"] == "done"
    ]
    if not done_episodes:
        raise RpcDomainError(_ERR_NO_ANALYSIS, "没有已完成分析的集，请先运行智能分析")

    job_id = context.job_store.create("narration", ref_id=project_id)
    cancel_event = threading.Event()
    context.cancel_events[job_id] = cancel_event
    context.executor.submit(
        _run_generation, context, job_id, project_id, done_episodes, modes, cancel_event
    )
    return {"job_id": job_id}


def list_plans(context: AppContext, params: dict[str, Any]) -> list[dict[str, Any]]:
    return plans_repo.list_by_project(context.conn, str(params.get("project_id", "")))


def _run_generation(
    context: AppContext,
    job_id: str,
    project_id: str,
    episodes: list[dict[str, Any]],
    modes: list[str],
    cancel_event: threading.Event,
) -> None:
    """逐模式生成编排；intro 额外合成 TTS 引子。单模式失败不中断其余。"""
    context.job_store.mark_running(job_id)
    project = projects_repo.get(context.conn, project_id)
    if project is None:
        raise ValueError("项目不存在")
    settings = dict(context.settings)
    settings["_project_name"] = str(project["name"])
    analysis_record = analysis_repo.get(context.conn, str(episodes[0]["id"]))
    if analysis_record is not None and analysis_record["genre"]:
        settings["_genre"] = str(analysis_record["genre"])
    total = len(modes)
    try:
        for index, mode in enumerate(modes):
            if cancel_event.is_set():
                context.job_store.mark_cancelled(job_id)
                return
            percent = index / total * 100
            context.job_store.set_progress(job_id, percent)
            context.notifier.progress(job_id, percent, f"生成{_mode_label(mode)}编排")
            _generate_one(context, mode, episodes, settings)
        context.job_store.mark_completed(job_id)
    except Exception as exc:
        context.job_store.mark_failed(job_id, str(exc))
        context.notifier.log("error", f"编排生成失败: {exc}")
    finally:
        context.cancel_events.pop(job_id, None)


def _generate_one(
    context: AppContext,
    mode: str,
    episodes: list[dict[str, Any]],
    settings: dict[str, str],
) -> None:
    """对首个已完成集生成编排（跨集编排随 P1 扩展）。"""
    episode = episodes[0]
    episode_id = str(episode["id"])
    record = analysis_repo.get(context.conn, episode_id)
    if record is None:
        raise ValueError("分析记录缺失")
    conflicts = _parse_conflicts(record["conflict_scores"])
    highlights = _parse_highlights(record["highlights"])
    asr_segments = narration_pipeline.parse_asr_segments(record["asr_segments"])
    audio = narration_pipeline.parse_audio_features(record["audio_features"])

    plan = narration_pipeline.build_plan(
        mode,
        episode_id,
        conflicts,
        highlights,
        asr_segments,
        audio,
        settings,
    )
    if mode in ("intro_narration", "cross_narration", "ultra_short_hook", "full_narration"):
        tts_dir = context.work_dir / "tts"
        plan = narration_pipeline.synthesize_narration_texts(plan, settings, tts_dir)
    plans_repo.create(
        context.conn,
        str(episode["project_id"]),
        mode,
        [episode_id],
        plan.model_dump(),
    )


def _parse_conflicts(raw: str | None) -> list[ConflictScore]:
    return [ConflictScore.model_validate(item) for item in json.loads(raw or "[]")]


def _parse_highlights(raw: str | None) -> list[HighlightSegment]:
    return [HighlightSegment.model_validate(item) for item in json.loads(raw or "[]")]


def _mode_label(mode: str) -> str:
    return {"raw_clip": "纯原片剪辑", "intro_narration": "片头解说"}.get(mode, mode)

