"""analysis 命名空间：start / status / cancel / results（长任务 job 模式）。"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from dramaclip.api.analysis_job import (
    _analyze_one,  # noqa: F401 - 测试经 analysis_api._analyze_one 直调，引用面保留
    _current_signature,
    _run_job,
    _source_stale,
)
from dramaclip.api.context import AppContext, llm_trace_dir
from dramaclip.engines.analysis import prescreen as prescreen_engine
from dramaclip.engines.analysis.models import (
    AsrSegment,
    AudioFeatures,
    EpisodeRawAnalysis,
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
_ERR_ANALYSIS_BUSY = -32205


def register(router: Router, context: AppContext) -> None:
    router.register("analysis.prescreen", lambda params: prescreen(context, params))
    router.register("analysis.update_asr", lambda params: update_asr(context, params))
    router.register("analysis.resync_semantic", lambda params: resync_semantic(context, params))
    router.register("analysis.start", lambda params: start(context, params))
    router.register("analysis.status", lambda params: status(context, params))
    router.register("analysis.cancel", lambda params: cancel(context, params))
    router.register("analysis.results", lambda params: results(context, params))
    router.register(
        "analysis.export_transcripts", lambda params: export_transcripts(context, params)
    )


def autostart_after_scan(
    context: AppContext, project_id: str, episode_count: int
) -> dict[str, Any] | None:
    """扫集成功后按 analysis.full_threshold 调度：≤N 全量分析，>N 预筛后再分析入选集。

    设置里没有该键（测试夹具）或没有 job 运行时：什么都不做。
    生产 load() 必带默认 15。
    """
    settings = getattr(context, "settings", None)
    if not isinstance(settings, dict) or "analysis.full_threshold" not in settings:
        return None
    if getattr(context, "job_store", None) is None or getattr(context, "executor", None) is None:
        return None
    if _active_ingest_job(context, project_id) is not None:
        return None
    threshold = max(1, min(config.get_int(settings, "analysis.full_threshold"), 80))
    if episode_count <= threshold:
        return start(context, {"project_id": project_id})
    return prescreen(context, {"project_id": project_id, "then_analyze": True})


def _active_ingest_job(context: AppContext, project_id: str) -> dict[str, Any] | None:
    for job in context.job_store.list_recent(limit=50, active_only=True):
        if job.get("ref_id") == project_id and job.get("type") in ("analysis", "prescreen"):
            return job
    return None


def _assert_no_active_ingest(context: AppContext, project_id: str) -> None:
    """并发守卫：同项目同时只允许一个分析/预筛任务。

    双跑不是无害的并行：两条管线会向同一个 work_dir 写同名中间 wav（两个
    ffmpeg 同时写一个文件），还会互相覆盖集状态——「能开新任务即说明无并发」
    是假设不是约束，这里把它变成约束。
    """
    active = _active_ingest_job(context, project_id)
    if active is not None:
        raise RpcDomainError(
            _ERR_ANALYSIS_BUSY,
            f"该项目已有进行中的任务（{active.get('type')} {active.get('id')}），"
            "请等待完成或取消后再开始",
        )


def prescreen(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """阶段一：批量轻量预筛（原案 3附），结果落 episode_prescreen 并推荐。"""
    project_id = str(params.get("project_id", ""))
    if projects_repo.get(context.conn, project_id) is None:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
    _assert_no_active_ingest(context, project_id)
    targets = [
        episode
        for episode in episodes_repo.list_by_project(context.conn, project_id)
        if episode["status"] in ("pending", "prescreened")
        # done 集源被换 → 预筛产物同样由源派生，纳入重筛（B8）
        or (episode["status"] == "done" and _source_stale(context, episode))
    ]
    if not targets:
        raise RpcDomainError(_ERR_NO_EPISODES, "没有待预筛的集")
    job_id = context.job_store.create("prescreen", ref_id=project_id)
    cancel_event = threading.Event()
    context.cancel_events[job_id] = cancel_event
    then_analyze = bool(params.get("then_analyze", False))
    context.executor.submit(
        context.notifier.tracked(
            job_id, _run_prescreen, context, job_id, project_id, targets, cancel_event, then_analyze
        )
    )
    return {"job_id": job_id}


def _run_prescreen(
    context: AppContext,
    job_id: str,
    project_id: str,
    targets: list[dict[str, Any]],
    cancel_event: threading.Event,
    then_analyze: bool = False,
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
            if episode["status"] == "done":
                context.notifier.log(
                    "warn",
                    f"第{episode['episode_number']}集 源已变更，重新预筛",
                    job_id=job_id,
                )
            signature = _current_signature(context, episode)
            if signature is not None:
                episodes_repo.set_source_signature(context.conn, episode_id, signature)
            episodes_repo.set_status(context.conn, episode_id, "prescreened")
        context.job_store.set_progress(job_id, 100.0, "预筛完成")
        context.notifier.progress(job_id, 100.0, "预筛完成")
        context.job_store.mark_completed(job_id)
    except Exception as exc:
        context.job_store.mark_failed(job_id, str(exc))
        context.notifier.log("error", f"预筛失败: {exc}")
    finally:
        context.cancel_events.pop(job_id, None)
    # then_analyze 的移交必须在任务终态之后、且在 mark_failed 的 except 之外：
    # start() 的失败不该回写已完成的预筛任务（对终态二次迁移会抛错逃逸）。
    if then_analyze:
        try:
            recommended_ids = [
                str(episode["id"])
                for episode in targets
                if _prescreen_recommended(context, str(episode["id"]))
            ]
            if recommended_ids:
                start(context, {"project_id": project_id, "episode_ids": recommended_ids})
        except Exception as exc:  # noqa: BLE001 - 移交失败如实留痕，不连坐已完成的预筛
            context.notifier.log("error", f"预筛完成但自动分析未启动: {exc}")


def _prescreen_recommended(context: AppContext, episode_id: str) -> bool:
    row = prescreen_repo.get(context.conn, episode_id)
    return bool(row and row.get("recommended"))


def start(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    project_id = str(params.get("project_id", ""))
    if projects_repo.get(context.conn, project_id) is None:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
    _assert_no_active_ingest(context, project_id)
    episode_ids = params.get("episode_ids")
    if episode_ids is None:
        # analyzing 一并纳入：能开新任务即说明无并发分析，该状态必为崩溃/中断残留
        # done 但源签名失配（B8）：源被换过，旧 ASR/场景结果不可信，强制重分析
        targets = [
            ep
            for ep in episodes_repo.list_by_project(context.conn, project_id)
            if ep["status"] in ("pending", "prescreened", "failed", "analyzing")
            or (ep["status"] == "done" and _source_stale(context, ep))
        ]
    else:
        wanted = [str(item) for item in episode_ids]
        targets = episodes_repo.list_by_ids(context.conn, wanted)
        if len(targets) != len(wanted):
            raise RpcDomainError(_ERR_JOB_NOT_FOUND, "episode_ids 含无效项")
    if not targets:
        raise RpcDomainError(_ERR_NO_EPISODES, "没有待分析的集")

    job_id = context.job_store.create("analysis", ref_id=project_id)
    # 建单即整批标 analyzing：前置的全剧 OCR/热词挖掘要逐集跑数分钟，期间集状态
    # 不能滞留旧值（否则界面整批显示 failed/pending 一动不动，用户无从判断是否受理）。
    # 未真正处理到的集由 _run_job finally 回滚；崩溃残留下次启动被 reset_stale_analyzing 清扫。
    for episode in targets:
        episodes_repo.set_status(context.conn, str(episode["id"]), "analyzing")
    cancel_event = threading.Event()
    context.cancel_events[job_id] = cancel_event
    context.executor.submit(
        context.notifier.tracked(
            job_id, _run_job, context, job_id, project_id, targets, cancel_event
        )
    )
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


def _srt_ts(seconds: float) -> str:
    """SRT 时间轴：00:00:01,500（逗号毫秒）。"""
    total_ms = max(0, round(float(seconds) * 1000))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _safe_filename(name: str) -> str:
    """Windows 文件名非法字符替换为下划线。"""
    return re.sub(r'[\/:*?"<>|]', "_", name).strip() or "未命名"


def export_transcripts(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """全部已分析集 → 逐集 SRT + 合并全剧台词 TXT，一次导出（2026-10-09 业主追加）。

    产物落 data/exports/transcripts/<剧名>/，前端 revealInFolder 直达。
    SRT 用融合转写结果（台词保护区的同源数据），放回视频旁即可被「同名 .srt
    优先」机制在下次分析时当金标准。未分析的集跳过并计数，不挡其他集。
    """
    project_id = str(params.get("project_id", ""))
    project = projects_repo.get(context.conn, project_id)
    if project is None:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
    episodes = episodes_repo.list_by_project(context.conn, project_id)
    safe_name = _safe_filename(str(project["name"]))
    out_dir = context.data_dir / "exports" / "transcripts" / safe_name
    out_dir.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    combined: list[str] = [f"《{project['name']}》全剧台词", ""]
    exported = 0
    skipped = 0
    for episode in episodes:
        if episode["status"] != "done":
            skipped += 1
            continue
        record = analysis_repo.get(context.conn, str(episode["id"]))
        raw = record.get("asr_segments") if record is not None else None
        try:
            segs = [AsrSegment.model_validate(item) for item in json.loads(str(raw or "[]"))]
        except (TypeError, json.JSONDecodeError, ValidationError):
            segs = []
        if not segs:
            skipped += 1
            continue
        number = int(episode["episode_number"])
        srt_lines: list[str] = []
        txt_lines: list[str] = [f"【第{number}集】"]
        for index, seg in enumerate(segs, start=1):
            srt_lines.append(str(index))
            srt_lines.append(f"{_srt_ts(seg.start)} --> {_srt_ts(seg.end)}")
            srt_lines.append(seg.text.strip())
            srt_lines.append("")
            txt_lines.append(seg.text.strip())
        srt_name = f"{_safe_filename(str(episode['name']))}.srt"
        (out_dir / srt_name).write_text("\n".join(srt_lines) + "\n", encoding="utf-8")
        files.append(srt_name)
        combined.extend(txt_lines)
        combined.append("")
        exported += 1
    txt_path = out_dir / f"{safe_name}_全剧台词.txt"
    txt_path.write_text("\n".join(combined) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "dir": str(out_dir),
        "txt_path": str(txt_path),
        "files": files,
        "exported": exported,
        "skipped": skipped,
    }


def update_asr(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """整列表替换 ASR 段（用户修正转写错误/删幻觉段）；保留下游已生成的语义结果。"""
    project_id = str(params.get("project_id", ""))
    episode_id = str(params.get("episode_id", ""))
    if projects_repo.get(context.conn, project_id) is None:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
    episode = episodes_repo.get(context.conn, episode_id)
    if episode is None or str(episode["project_id"]) != project_id:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"集不存在: {episode_id}")
    if episode["status"] == "analyzing":
        # 与进行中的分析并发改写会被任务随后的 update_asr_segments 覆盖——拒掉而不是让用户白改。
        raise RpcDomainError(_ERR_SEGMENT_INVALID, "该集正在分析中，请等分析完成后再修改转写")
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
    context.executor.submit(
        context.notifier.tracked(job_id, _run_resync, context, job_id, episode_id, cancel_event)
    )
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
                SceneInfo.model_validate(item) for item in json.loads(record["scene_data"] or "[]")
            ],
            audio=AudioFeatures.model_validate(json.loads(record["audio_features"] or "{}")),
        )
        if cancel_event.is_set():
            context.job_store.mark_cancelled(job_id)
            return
        context.notifier.progress(job_id, 40.0, "语义分析中")
        semantic_result = semantic_pipeline.enhance(
            raw,
            context.settings,
            trace_dir=llm_trace_dir(context),
            trace_tag=episode_id,
        )
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
    visual_map: dict[str, dict[str, Any]] = {}
    for episode in episodes:
        episode_id = str(episode["id"])
        prescreen = prescreen_repo.get(context.conn, episode_id)
        record = analysis_repo.get(context.conn, episode_id)
        segments = _loads_list(record["asr_segments"]) if record else []
        highlights = _loads_list(record["highlights"]) if record else []
        conflict_scores = _loads_list(record["conflict_scores"]) if record else []
        if segments:
            asr_map[episode_id] = segments
        if highlights:
            highlights_map[episode_id] = highlights
        if conflict_scores:
            conflict_map[episode_id] = conflict_scores
        if prescreen is not None:
            prescreen_map[episode_id] = prescreen
        visual = None
        if record and record["visual_track"]:
            try:
                visual = json.loads(record["visual_track"])
            except (TypeError, json.JSONDecodeError, ValueError):
                visual = None
        if isinstance(visual, dict) and visual.get("frames"):
            visual_map[episode_id] = visual
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
        peak_dbfs, clipping = _audio_peak(record)
        if clipping:
            entry["clipping"] = True
            if peak_dbfs is not None:
                entry["peak_dbfs"] = peak_dbfs
        summary.append(entry)
    return {
        "episodes": summary,
        "asr_segments": asr_map,
        "visual_tracks": visual_map,
        "highlights": highlights_map,
        "conflict_scores": conflict_map,
        "prescreen": prescreen_map,
    }


def _loads_list(raw: Any) -> list[Any]:
    """JSON 列宽容解析：一行坏数据不能炸掉整个 results RPC（与 export_transcripts
    的守卫同口径）。坏行降级为空列表——丢的是那一列的展示，不是整个接口。"""
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _scene_count(record: dict[str, Any] | None) -> int:
    if record is None or not record["scene_data"]:
        return 0
    return len(_loads_list(record["scene_data"]))


def _audio_peak(record: dict[str, Any] | None) -> tuple[float | None, bool]:
    """源音频削顶：成片限幅只能压电平，不能把平顶长回来。"""
    if record is None or not record["audio_features"]:
        return None, False
    try:
        audio = AudioFeatures.model_validate(json.loads(record["audio_features"]))
    except (json.JSONDecodeError, ValueError):
        return None, False
    return audio.peak_dbfs, audio.clipping

