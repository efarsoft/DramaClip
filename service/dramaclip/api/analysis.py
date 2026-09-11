"""analysis 命名空间：start / status / cancel / results（长任务 job 模式）。"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.engines.analysis import fusion, pipeline, runtime, subtitle_ocr
from dramaclip.engines.analysis import prescreen as prescreen_engine
from dramaclip.engines.analysis.models import (
    AsrSegment,
    AudioFeatures,
    EpisodeRawAnalysis,
    OcrSegment,
    SceneInfo,
)
from dramaclip.engines.semantic import pipeline as semantic_pipeline
from dramaclip.infra import config
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import prescreen as prescreen_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.rpc import Router, RpcDomainError

_ERR_PROJECT_NOT_FOUND = -32101
_ERR_JOB_NOT_FOUND = -32201
_ERR_NO_EPISODES = -32202
_ERR_NO_ANALYSIS = -32203
_ERR_SEGMENT_INVALID = -32204


def register(router: Router, context: AppContext) -> None:
    router.register("analysis.prescreen", lambda params: prescreen(context, params))
    router.register("analysis.update_asr", lambda params: update_asr(context, params))
    router.register("analysis.resync_semantic", lambda params: resync_semantic(context, params))
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
                threshold=float(config.get_int(context.settings, "analysis.prescreen_threshold")),
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
        context.job_store.set_progress(job_id, 100.0, "预筛完成")
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
        # analyzing 一并纳入：能开新任务即说明无并发分析，该状态必为崩溃/中断残留
        targets = [
            ep for ep in episodes_repo.list_by_project(context.conn, project_id)
            if ep["status"] in ("pending", "prescreened", "failed", "analyzing")
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


def update_asr(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """整列表替换 ASR 段（用户修正转写错误/删幻觉段）；保留下游已生成的语义结果。"""
    project_id = str(params.get("project_id", ""))
    episode_id = str(params.get("episode_id", ""))
    if projects_repo.get(context.conn, project_id) is None:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
    episode = episodes_repo.get(context.conn, episode_id)
    if episode is None or str(episode["project_id"]) != project_id:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"集不存在: {episode_id}")
    record = analysis_repo.get(context.conn, episode_id)
    if record is None:
        raise RpcDomainError(_ERR_NO_ANALYSIS, "该集尚无分析结果")

    raw_segments = params.get("segments")
    if not isinstance(raw_segments, list):
        raise RpcDomainError(_ERR_SEGMENT_INVALID, "segments 必须为数组")
    cleaned: list[dict[str, Any]] = []
    for item in raw_segments:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        try:
            start = float(item.get("start", 0))
            end = float(item.get("end", 0))
        except (TypeError, ValueError):
            continue
        if end <= start or not text:
            continue
        cleaned.append(
            {
                "start": start,
                "end": end,
                "text": text,
                "speaker": item.get("speaker"),
                "emotion": item.get("emotion"),
            }
        )
    analysis_repo.update_asr_segments(
        context.conn, episode_id, json.dumps(cleaned, ensure_ascii=False)
    )
    return {"ok": True, "count": len(cleaned)}


def resync_semantic(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """仅重跑语义层（修正 ASR 后刷新冲突/高光/题材），不重转写。"""
    project_id = str(params.get("project_id", ""))
    episode_id = str(params.get("episode_id", ""))
    if projects_repo.get(context.conn, project_id) is None:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
    episode = episodes_repo.get(context.conn, episode_id)
    if episode is None or str(episode["project_id"]) != project_id:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"集不存在: {episode_id}")
    if analysis_repo.get(context.conn, episode_id) is None:
        raise RpcDomainError(_ERR_NO_ANALYSIS, "该集尚无分析结果")
    job_id = context.job_store.create("semantic", ref_id=episode_id)
    cancel_event = threading.Event()
    context.cancel_events[job_id] = cancel_event
    context.executor.submit(_run_resync, context, job_id, episode_id, cancel_event)
    return {"job_id": job_id}


def _run_resync(
    context: AppContext,
    job_id: str,
    episode_id: str,
    cancel_event: threading.Event,
) -> None:
    context.job_store.mark_running(job_id)
    try:
        record = analysis_repo.get(context.conn, episode_id)
        if record is None:
            raise ValueError("分析记录已被删除")
        context.notifier.progress(job_id, 10.0, "重建第一层结果")
        raw = EpisodeRawAnalysis(
            asr_segments=[
                AsrSegment.model_validate(item) for item in json.loads(record["asr_segments"])
            ],
            scenes=[
                SceneInfo.model_validate(item)
                for item in json.loads(record["scene_data"] or "[]")
            ],
            audio=AudioFeatures.model_validate(json.loads(record["audio_features"] or "{}")),
        )
        if cancel_event.is_set():
            context.job_store.mark_cancelled(job_id)
            return
        context.notifier.progress(job_id, 40.0, "语义分析中")
        semantic_result = semantic_pipeline.enhance(raw, context.settings)
        analysis_repo.update_semantic(
            context.conn,
            episode_id,
            conflict_scores=json.dumps([s.model_dump() for s in semantic_result.conflict_scores]),
            highlights=json.dumps([h.model_dump() for h in semantic_result.highlights]),
            genre=semantic_result.genre or None,
        )
        context.job_store.set_progress(job_id, 100.0, "语义结果已刷新")
        context.notifier.progress(job_id, 100.0, "语义结果已刷新")
        context.job_store.mark_completed(job_id)
    except Exception as exc:
        context.job_store.mark_failed(job_id, str(exc))
        context.notifier.log("error", f"语义重算失败: {exc}")
    finally:
        context.cancel_events.pop(job_id, None)


def results(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    project_id = str(params.get("project_id", ""))
    if projects_repo.get(context.conn, project_id) is None:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
    episodes = episodes_repo.list_by_project(context.conn, project_id)
    summary: list[dict[str, Any]] = []
    asr_map: dict[str, list[dict[str, Any]]] = {}
    highlights_map: dict[str, list[dict[str, Any]]] = {}
    conflict_map: dict[str, list[dict[str, Any]]] = {}
    prescreen_map: dict[str, dict[str, Any]] = {}
    for episode in episodes:
        episode_id = str(episode["id"])
        prescreen = prescreen_repo.get(context.conn, episode_id)
        record = analysis_repo.get(context.conn, episode_id)
        segments = json.loads(record["asr_segments"]) if record else []
        highlights = json.loads(record["highlights"]) if record and record["highlights"] else []
        conflict_scores = (
            json.loads(record["conflict_scores"]) if record and record["conflict_scores"] else []
        )
        if segments:
            asr_map[episode_id] = segments
        if highlights:
            highlights_map[episode_id] = highlights
        if conflict_scores:
            conflict_map[episode_id] = conflict_scores
        if prescreen is not None:
            prescreen_map[episode_id] = prescreen
        entry: dict[str, Any] = {
            "episode_id": episode_id,
            "episode_number": episode["episode_number"],
            "status": episode["status"],
            "asr_segment_count": len(segments),
            "scene_count": _scene_count(record),
            "highlight_count": len(highlights),
            "prescreen_score": prescreen["prescreen_score"] if prescreen else None,
            "recommended": bool(prescreen["recommended"]) if prescreen else None,
        }
        genre = record["genre"] if record else None
        if genre:
            entry["genre"] = str(genre)
        summary.append(entry)
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
        context.job_store.set_progress(job_id, round(overall, 1), f"{label} {message}")
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
    asr_segments, ocr_segments = _fuse_ocr(context, episode, raw.asr_segments)
    analysis_repo.upsert(
        context.conn,
        episode_id,
        asr_segments=json.dumps([seg.model_dump() for seg in asr_segments]),
        scene_data=json.dumps([scene.model_dump() for scene in raw.scenes]),
        audio_features=raw.audio.model_dump_json(),
        conflict_scores=json.dumps([s.model_dump() for s in semantic_result.conflict_scores]),
        highlights=json.dumps([h.model_dump() for h in semantic_result.highlights]),
        genre=semantic_result.genre or None,
        ocr_segments=(
            json.dumps([o.model_dump() for o in ocr_segments]) if ocr_segments else None
        ),
    )
    episodes_repo.set_status(context.conn, episode_id, "done")
    return True


def _fuse_ocr(
    context: AppContext,
    episode: dict[str, Any],
    asr: list[AsrSegment],
) -> tuple[list[AsrSegment], list[OcrSegment] | None]:
    """硬字幕 OCR 通道 + 融合（analysis.ocr_enabled 默认开）。

    依赖缺失（ml extras 未装）静默回退纯 ASR；运行失败留痕不阻塞分析。
    """
    if context.settings.get("analysis.ocr_enabled", "1") != "1":
        return asr, None
    duration = float(episode["duration"] or 0)
    if duration <= 0:
        return asr, None
    try:
        ocr = subtitle_ocr.extract_subtitles(
            Path(str(episode["source_path"])),
            context.work_dir / f"ocr_{episode["id"]}",
            duration_s=duration,
        )
    except ImportError:
        return asr, None  # rapidocr 未安装：ml extras 约定的纯 ASR 路径
    except Exception as exc:  # noqa: BLE001 - OCR 失败不影响分析主链路
        context.notifier.log("warn", f"OCR 字幕通道失败（不影响分析）: {exc}")
        return asr, None
    if not ocr:
        return asr, None
    return fusion.fuse(asr, ocr), ocr

