"""analysis 命名空间：start / status / cancel / results（长任务 job 模式）。"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.engines.analysis import pipeline, runtime
from dramaclip.engines.analysis import prescreen as prescreen_engine
from dramaclip.engines.semantic import pipeline as semantic_pipeline
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import prescreen as prescreen_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.rpc import Router, RpcDomainError

_ERR_PROJECT_NOT_FOUND = -32101
_ERR_JOB_NOT_FOUND = -32201
_ERR_NO_EPISODES = -32202


def register(router: Router, context: AppContext) -> None:
    router.register("analysis.prescreen", lambda params: prescreen(context, params))
    router.register("analysis.start", lambda params: start(context, params))
    router.register("analysis.status", lambda params: status(context, params))
    router.register("analysis.cancel", lambda params: cancel(context, params))
    router.register("analysis.results", lambda params: results(context, params))


def prescreen(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """阶段一：批量轻量预筛（原案 3附），结果落 episode_prescreen 并推荐。"""
    project_id = str(params.get("project_id", ""))
    if projects_repo.get(context.conn, project_id) is None:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
    targets = [
        episode
        for episode in episodes_repo.list_by_project(context.conn, project_id)
        if episode["status"] in ("pending", "prescreened")
    ]
    if not targets:
        raise RpcDomainError(_ERR_NO_EPISODES, "没有待预筛的集")
    job_id = context.job_store.create("prescreen", ref_id=project_id)
    cancel_event = threading.Event()
    context.cancel_events[job_id] = cancel_event
    context.executor.submit(_run_prescreen, context, job_id, targets, cancel_event)
    return {"job_id": job_id}


def _run_prescreen(
    context: AppContext,
    job_id: str,
    targets: list[dict[str, Any]],
    cancel_event: threading.Event,
) -> None:
    from pathlib import Path

    context.job_store.mark_running(job_id)
    total = len(targets)
    try:
        for index, episode in enumerate(targets):
            if cancel_event.is_set():
                context.job_store.mark_cancelled(job_id)
                return
            episode_id = str(episode["id"])
            context.notifier.progress(
                job_id, round(index / total * 100, 1), f"第{episode['episode_number']}集 预筛中"
            )
            result = prescreen_engine.prescreen_episode(
                Path(str(episode["source_path"])),
                context.work_dir / "prescreen" / f"{episode_id}.wav",
            )
            prescreen_repo.upsert(
                context.conn,
                episode_id,
                audio_peak_density=result["audio_peak_density"],
                scene_cut_density=result["scene_cut_density"],
                voice_activity_ratio=result["voice_activity_ratio"],
                motion_intensity=result["motion_intensity"],
                prescreen_score=result["prescreen_score"],
                recommended=bool(result["recommended"]),
            )
            episodes_repo.set_status(context.conn, episode_id, "prescreened")
        context.job_store.set_progress(job_id, 100.0)
        context.notifier.progress(job_id, 100.0, "预筛完成")
        context.job_store.mark_completed(job_id)
    except Exception as exc:
        context.job_store.mark_failed(job_id, str(exc))
        context.notifier.log("error", f"预筛失败: {exc}")
    finally:
        context.cancel_events.pop(job_id, None)


def start(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    project_id = str(params.get("project_id", ""))
    if projects_repo.get(context.conn, project_id) is None:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
    episode_ids = params.get("episode_ids")
    if episode_ids is None:
        targets = [
            ep for ep in episodes_repo.list_by_project(context.conn, project_id)
            if ep["status"] in ("pending", "prescreened", "failed")
        ]
    else:
        wanted = [str(item) for item in episode_ids]
        targets = episodes_repo.list_by_ids(context.conn, wanted)
        if len(targets) != len(wanted):
            raise RpcDomainError(_ERR_JOB_NOT_FOUND, "episode_ids 含无效项")
    if not targets:
        raise RpcDomainError(_ERR_NO_EPISODES, "没有待分析的集")

    job_id = context.job_store.create("analysis", ref_id=project_id)
    cancel_event = threading.Event()
    context.cancel_events[job_id] = cancel_event
    context.executor.submit(_run_job, context, job_id, project_id, targets, cancel_event)
    return {"job_id": job_id}


def status(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    job_id = str(params.get("job_id", ""))
    job = context.job_store.get(job_id)
    if job is None:
        raise RpcDomainError(_ERR_JOB_NOT_FOUND, f"任务不存在: {job_id}")
    episodes = [
        {"episode_id": ep["id"], "status": ep["status"]}
        for ep in episodes_repo.list_by_project(context.conn, str(job["ref_id"]))
    ]
    return {
        "job_id": job_id,
        "status": job["status"],
        "progress": job["progress"],
        "error": job["error"],
        "episodes": episodes,
    }


def cancel(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    job_id = str(params.get("job_id", ""))
    if context.job_store.get(job_id) is None:
        raise RpcDomainError(_ERR_JOB_NOT_FOUND, f"任务不存在: {job_id}")
    event = context.cancel_events.get(job_id)
    if event is not None:
        event.set()
    return {"ok": True}


def results(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    project_id = str(params.get("project_id", ""))
    if projects_repo.get(context.conn, project_id) is None:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
    episodes = episodes_repo.list_by_project(context.conn, project_id)
    summary: list[dict[str, Any]] = []
    asr_map: dict[str, list[dict[str, Any]]] = {}
    highlights_map: dict[str, list[dict[str, Any]]] = {}
    conflict_map: dict[str, list[dict[str, Any]]] = {}
    for episode in episodes:
        record = analysis_repo.get(context.conn, str(episode["id"]))
        segments = json.loads(record["asr_segments"]) if record else []
        highlights = json.loads(record["highlights"]) if record and record["highlights"] else []
        conflict_scores = (
            json.loads(record["conflict_scores"]) if record and record["conflict_scores"] else []
        )
        episode_id = str(episode["id"])
        if segments:
            asr_map[episode_id] = segments
        if highlights:
            highlights_map[episode_id] = highlights
        if conflict_scores:
            conflict_map[episode_id] = conflict_scores
        summary.append(
            {
                "episode_id": episode_id,
                "episode_number": episode["episode_number"],
                "status": episode["status"],
                "asr_segment_count": len(segments),
                "scene_count": _scene_count(record),
                "highlight_count": len(highlights),
                "prescreen_score": prescreen["prescreen_score"] if prescreen else None,
                "recommended": bool(prescreen["recommended"]) if prescreen else None,
                "genre": (record or {}).get("genre") if record else None,
            }
        )
    return {
        "episodes": summary,
        "asr_segments": asr_map,
        "highlights": highlights_map,
        "conflict_scores": conflict_map,
        "prescreen": prescreen_map,
    }


def _scene_count(record: dict[str, Any] | None) -> int:
    if record is None or not record["scene_data"]:
        return 0
    return len(json.loads(record["scene_data"]))


def _run_job(
    context: AppContext,
    job_id: str,
    project_id: str,
    targets: list[dict[str, Any]],
    cancel_event: threading.Event,
) -> None:
    """执行池任务：逐集分析，单集失败不中断其余；进度经 jobs 表 + 通知双通道。"""
    context.job_store.mark_running(job_id)
    projects_repo.set_status(context.conn, project_id, "analyzing")
    total = len(targets)
    failures = 0
    language = runtime.language(context.settings)
    try:
        for index, episode in enumerate(targets):
            if cancel_event.is_set():
                context.job_store.mark_cancelled(job_id)
                return
            if not _analyze_one(context, job_id, episode, index, total, language, cancel_event):
                failures += 1
        context.job_store.mark_completed(job_id)
    except Exception as exc:  # 引擎级致命错误（如模型加载失败）
        context.job_store.mark_failed(job_id, str(exc))
        context.notifier.log("error", f"分析任务失败: {exc}")
    finally:
        context.cancel_events.pop(job_id, None)
        projects_repo.set_status(context.conn, project_id, "ready")
        if failures:
            context.notifier.log("warn", f"分析完成，{failures}/{total} 集失败")


def _analyze_one(
    context: AppContext,
    job_id: str,
    episode: dict[str, Any],
    index: int,
    total: int,
    language: str,
    cancel_event: threading.Event,
) -> bool:
    """分析单集；返回是否成功（失败标记后继续其余集）。"""
    episode_id = str(episode["id"])
    label = f"第{episode['episode_number']}集"

    def report(percent: float, message: str) -> None:
        overall = (index + percent) / total * 100
        context.job_store.set_progress(job_id, round(overall, 1))
        context.notifier.progress(job_id, round(overall, 1), f"{label} {message}")

    episodes_repo.set_status(context.conn, episode_id, "analyzing")
    try:
        raw = pipeline.analyze_episode(
            video_path=Path(str(episode["source_path"])),
            work_dir=context.work_dir / episode_id,
            transcriber=context.analysis_runtime.transcriber(),
            language=language,
            cancel=cancel_event,
            report=report,
        )
        semantic_result = semantic_pipeline.enhance(raw, context.settings)
    except Exception as exc:
        episodes_repo.set_status(context.conn, episode_id, "failed")
        context.notifier.log("error", f"{label} 分析失败: {exc}")
        return False
    analysis_repo.upsert(
        context.conn,
        episode_id,
        asr_segments=json.dumps([seg.model_dump() for seg in raw.asr_segments]),
        scene_data=json.dumps([scene.model_dump() for scene in raw.scenes]),
        audio_features=raw.audio.model_dump_json(),
        conflict_scores=json.dumps([s.model_dump() for s in semantic_result.conflict_scores]),
        highlights=json.dumps([h.model_dump() for h in semantic_result.highlights]),
        genre=semantic_result.genre or None,
    )
    episodes_repo.set_status(context.conn, episode_id, "done")
    return True
