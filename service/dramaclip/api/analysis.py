"""analysis 命名空间：start / status / cancel / results（长任务 job 模式）。"""

from __future__ import annotations

import importlib
import json
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from dramaclip.api.context import AppContext, llm_trace_dir
from dramaclip.engines.analysis import (
    contact_sheet,
    fusion,
    pipeline,
    runtime,
    subtitle_ocr,
)
from dramaclip.engines.analysis import (
    hotwords as hotwords_engine,
)
from dramaclip.engines.analysis import prescreen as prescreen_engine
from dramaclip.engines.analysis.models import (
    AsrSegment,
    AudioFeatures,
    EpisodeRawAnalysis,
    OcrSegment,
    SceneInfo,
)
from dramaclip.engines.semantic import pipeline as semantic_pipeline
from dramaclip.engines.vision import runtime as vision_engine
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


# ── B8 源失效判据：签名 = md5(path|size|mtime_ns|ocr_channel)，见 pipeline.source_signature ──


def _ocr_channel_available(context: AppContext) -> bool:
    """OCR 字幕通道是否可用：设置开关开启 + rapidocr（ml extras）已安装。

    可用性参与源签名：通道缺失时产物是纯 ASR 降级版，依赖装好后签名失配即强制重算，
    降级结果不会在「条件已修复」后永久滞留。
    """
    if context.settings.get("analysis.ocr_enabled", "1") != "1":
        return False
    try:
        importlib.import_module("rapidocr_onnxruntime")
    except ImportError:
        return False
    return True


def _current_signature(context: AppContext, episode: dict[str, Any]) -> str | None:
    return pipeline.source_signature(
        Path(str(episode["source_path"])),
        ocr_channel=_ocr_channel_available(context),
    )


def _source_stale(context: AppContext, episode: dict[str, Any]) -> bool:
    """库里签名 ≠ 当前源签名（含旧库 NULL 首次）→ 既有分析/预筛产物不可信，需重算。

    源文件不可读时返回 False：缺文件的失败交给分析引擎自己报错留痕，不做签名失效。
    """
    current = _current_signature(context, episode)
    if current is None:
        return False
    return episode.get("source_signature") != current


def prescreen(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """阶段一：批量轻量预筛（原案 3附），结果落 episode_prescreen 并推荐。"""
    project_id = str(params.get("project_id", ""))
    if projects_repo.get(context.conn, project_id) is None:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
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
        if then_analyze:
            recommended_ids = [
                str(episode["id"])
                for episode in targets
                if _prescreen_recommended(context, str(episode["id"]))
            ]
            if recommended_ids:
                start(context, {"project_id": project_id, "episode_ids": recommended_ids})
    except Exception as exc:
        context.job_store.mark_failed(job_id, str(exc))
        context.notifier.log("error", f"预筛失败: {exc}")
    finally:
        context.cancel_events.pop(job_id, None)


def _prescreen_recommended(context: AppContext, episode_id: str) -> bool:
    row = prescreen_repo.get(context.conn, episode_id)
    return bool(row and row.get("recommended"))


def start(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    project_id = str(params.get("project_id", ""))
    if projects_repo.get(context.conn, project_id) is None:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
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
        peak_dbfs, clipping = _audio_peak(record)
        if clipping:
            entry["clipping"] = True
            if peak_dbfs is not None:
                entry["peak_dbfs"] = peak_dbfs
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


def _audio_peak(record: dict[str, Any] | None) -> tuple[float | None, bool]:
    """源音频削顶：成片限幅只能压电平，不能把平顶长回来。"""
    if record is None or not record["audio_features"]:
        return None, False
    try:
        audio = AudioFeatures.model_validate(json.loads(record["audio_features"]))
    except (json.JSONDecodeError, ValueError):
        return None, False
    return audio.peak_dbfs, audio.clipping


def _restore_unprocessed(context: AppContext, targets: list[dict[str, Any]]) -> None:
    """把没真正处理到的目标集从 analyzing 回滚为入队前状态。

    start() 建单时整批标了 analyzing；取消/致命失败后没轮到的集不能滞留在
    analyzing（界面会误示仍在处理）。处理过的集已被置为 done/failed，不受影响；
    进程崩溃没走到这里的残留，由下次启动的 reset_stale_analyzing 清扫。
    """
    for episode in targets:
        episode_id = str(episode["id"])
        row = episodes_repo.get(context.conn, episode_id)
        if row is not None and row["status"] == "analyzing":
            episodes_repo.set_status(context.conn, episode_id, str(episode["status"]))


def _run_job(
    context: AppContext,
    job_id: str,
    project_id: str,
    targets: list[dict[str, Any]],
    cancel_event: threading.Event,
) -> None:
    """执行池任务：全剧 OCR→热词→逐集分析，单集失败不中断其余。"""
    context.job_store.mark_running(job_id)
    projects_repo.set_status(context.conn, project_id, "analyzing")
    vision = vision_engine.open_session(
        context.data_dir, context.data_dir / "models", context.settings
    )
    if vision is not None:
        context.notifier.log(
            "info", f"视觉轨启用（{vision.model_id}）：逐集画面理解将随分析进行", job_id=job_id
        )
    total = len(targets)
    failures = 0
    language = runtime.language(context.settings)
    if context.settings.get("analysis.ocr_enabled", "1") == "1" and not _ocr_channel_available(
        context
    ):
        # 降级打标：OCR 通道缺失 → 本轮产物是纯 ASR 降级版（无硬字幕融合）。
        # ocr_channel 参与源签名，装好 rapidocr 后签名失配自动强制重算。
        context.notifier.log(
            "warn",
            "OCR 字幕通道不可用（rapidocr 未安装），分析产物为纯 ASR 降级版；"
            "依赖就绪后相关集将自动重新分析",
            job_id=job_id,
        )
    try:
        # 挖掘阶段逐集播报：任务标签/进度通知可见（此前整批分析前几分钟毫无动静）
        # 挖掘阶段计入总进度前 30%：OCR 逐集要数分钟，恒 0% 会被当成卡死（业主实测反馈）
        def mining_report(done: int, count: int) -> None:
            percent = round(done / count * 30, 1) if count else 0.0
            message = f"全剧字幕热词挖掘 {done}/{count} 集"
            context.job_store.set_progress(job_id, percent, message)
            context.notifier.progress(job_id, percent, message)

        bars_by_episode, bands_by_episode, lines_by_episode, hotwords = _mine_hotwords(
            context, targets, cancel_event, on_episode=mining_report
        )
        for index, episode in enumerate(targets):
            if cancel_event.is_set():
                context.job_store.mark_cancelled(job_id)
                return
            episode_id = str(episode["id"])
            bars = bars_by_episode.get(episode_id)
            if not _analyze_one(
                context,
                job_id,
                episode,
                index,
                total,
                language,
                cancel_event,
                vision=vision,
                ocr_bars=bars,
                ocr_lines=lines_by_episode.get(episode_id),
                ocr_band=bands_by_episode.get(episode_id),
                hotwords=hotwords,
            ):
                failures += 1
        context.job_store.mark_completed(job_id)
    except Exception as exc:  # 引擎级致命错误（如模型加载失败）
        context.job_store.mark_failed(job_id, str(exc))
        context.notifier.log("error", f"分析任务失败: {exc}")
    finally:
        if vision is not None:
            vision.close()
        _restore_unprocessed(context, targets)
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
    *,
    vision: vision_engine.VisionSession | None = None,
    ocr_bars: list[OcrSegment] | None = None,
    ocr_band: tuple[float, float] | None = None,
    ocr_lines: list[tuple[float, float]] | None = None,
    hotwords: str = "",
) -> bool:
    """分析单集；返回是否成功（失败标记后继续其余集）。

    两段写入：第一层（转写/场景/音频/OCR）跑完立即落库、语义列显式清空，语义层
    完成**才**标 done——链路里最贵的是转写、最易挂的是 LLM，语义抖动不再连坐
    转写白跑。重入判据：签名相同 + 语义列为空 = 上轮死在语义层，跳过转写直补。
    """
    episode_id = str(episode["id"])
    label = f"第{episode['episode_number']}集"

    # 单调钳制：转写管线报完「分析完成 100%」后视觉轨还会续报——不钳会 100%→48% 回跳
    peak = [float("-inf")]

    def report(percent: float, message: str) -> None:
        overall = max(30 + (index + percent) / total * 70, peak[0])
        peak[0] = overall
        context.job_store.set_progress(job_id, round(overall, 1), f"{label} {message}")
        context.notifier.progress(job_id, round(overall, 1), f"{label} {message}")

    # 分析开始前取签名：产物对应的是这份源；分析中途源被换则存的是旧签名，
    # 下轮判定必然失配重算——宁多算一轮，不把新签名盖在旧源产物上。
    signature = _current_signature(context, episode)
    if (
        episode["status"] == "done"
        and signature is not None
        and episode.get("source_signature") != signature
    ):
        # B8 失效重算（源被换或旧库 NULL 签名）：留痕，防「源换了还静默用旧 ASR」
        context.notifier.log("warn", f"{label} 源已变更，重新分析", job_id=job_id)
    episodes_repo.set_status(context.conn, episode_id, "analyzing")
    try:
        stored = _resumable_raw(context, episode, signature)
        if stored is not None:
            context.notifier.log(
                "info", f"{label} 上轮语义层未完成：沿用转写结果，直接补语义", job_id=job_id
            )
            raw = stored
        else:
            raw = pipeline.analyze_episode(
                video_path=Path(str(episode["source_path"])),
                work_dir=context.work_dir / episode_id,
                transcriber=context.analysis_runtime.transcriber(),
                language=language,
                cancel=cancel_event,
                report=report,
                hotwords=hotwords,
            )
            asr_segments, ocr_segments, band, band_lines = _fuse_ocr(
                context, episode, raw.asr_segments, ocr_bars, ocr_band, ocr_lines
            )  # noqa: F841 - band_lines 落库见下方 subtitle_band
            ocr_json = (
                json.dumps([o.model_dump() for o in ocr_segments]) if ocr_segments else None
            )
            sheet = _contact_sheet(context, episode)
            frames = _describe_frames(context, vision, episode, episode_id, report)
            track: dict[str, Any] = {}
            if sheet is not None:
                track["contact_sheet"] = sheet
            if frames:
                track["frames"] = frames
                track["engine"] = vision.model_id if vision is not None else ""
            analysis_repo.upsert(
                context.conn,
                episode_id,
                asr_segments=json.dumps([seg.model_dump() for seg in asr_segments]),
                scene_data=json.dumps([scene.model_dump() for scene in raw.scenes]),
                audio_features=raw.audio.model_dump_json(),
                ocr_segments=ocr_json,
                visual_track=json.dumps(track) if track else None,
                # 覆盖数据链落库：{"band": [t,b], "lines": [[t,b],...]}（旧库为纯 list，
                # 读取端两种都认）。NULL=无硬字幕带/未探测/OCR 未装，消费端回退现状
                subtitle_band=(
                    json.dumps(
                        {"band": [band[0], band[1]], "lines": band_lines or []}
                        if band is not None
                        else None
                    )
                    if band is not None
                    else None
                ),
                # 语义列显式清空（upsert 传 None 即置 NULL）：此后任何时刻挂掉，
                # 重入判据都能识别「这份源的第一层已就绪，只欠语义」。
            )
            if signature is not None:
                episodes_repo.set_source_signature(context.conn, episode_id, signature)
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
        episodes_repo.mark_done(context.conn, episode_id)
        return True
    except Exception as exc:
        episodes_repo.set_status(context.conn, episode_id, "failed")
        context.notifier.log("error", f"{label} 分析失败: {exc}")
        return False


def _contact_sheet(context: AppContext, episode: dict[str, Any]) -> str | None:
    """生成逐集 contact sheet（视觉轨输入与预览资产），返回落库路径；失败仅留痕。

    分档语义：拼图是增强品不是必需品——ffmpeg 失败/时长缺失只记 warn 落 NULL，
    分析照常完成，消费端对 NULL 回退纯台词行为（同 subtitle_band 的 NULL 口径）。
    """
    try:
        out = context.data_dir / "contact_sheets" / f"{episode['id']}.png"
        contact_sheet.build_contact_sheet(
            Path(str(episode["source_path"])),
            out,
            duration_s=float(episode["duration"] or 0.0),
        )
        return str(out)
    except Exception as exc:
        context.notifier.log(
            "warn",
            f"第{episode['episode_number']}集 拼图生成失败（不影响分析）: {exc}",
        )
        return None


def _describe_frames(
    context: AppContext,
    vision: vision_engine.VisionSession | None,
    episode: dict[str, Any],
    episode_id: str,
    report: Callable[[float, str], None],
) -> list[dict[str, Any]]:
    """视觉轨逐图描述（P2b）：采样 16 帧 → 4 张一组多图请求 → 编号回填解析。

    会话由任务级持有（模型跨集复用）；任何失败按分档落 []——分析照常完成，
    消费端对空 frames 回退纯台词行为，重跑单集可补。
    """
    if vision is None:
        return []
    try:
        return vision.describe_episode(
            Path(str(episode["source_path"])),
            float(episode["duration"] or 0.0),
            context.work_dir / episode_id / "vl",
            on_progress=lambda frac, text: report(round(frac, 3), text),
        )
    except Exception as exc:
        context.notifier.log(
            "warn",
            f"第{episode['episode_number']}集 画面理解失败（不影响分析）: {exc}",
        )
        return []


def _resumable_raw(
    context: AppContext, episode: dict[str, Any], signature: str | None
) -> EpisodeRawAnalysis | None:
    """上轮死在语义层的残留可续跑时，从库里重建第一层产物；不可续返回 None。

    判据三条同时成立：源签名相同（转写产物属于这份源）、语义列为空（语义层没
    完成）、第一层产物能完整解析（半截/损坏的记录按不可续走全量重算）。
    """
    if signature is None or episode.get("source_signature") != signature:
        return None
    record = analysis_repo.get(context.conn, str(episode["id"]))
    if record is None or not record["asr_segments"] or record["conflict_scores"]:
        return None
    try:
        return EpisodeRawAnalysis(
            asr_segments=[
                AsrSegment.model_validate(item) for item in json.loads(record["asr_segments"])
            ],
            scenes=[
                SceneInfo.model_validate(item) for item in json.loads(record["scene_data"] or "[]")
            ],
            audio=AudioFeatures.model_validate(json.loads(record["audio_features"] or "{}")),
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _fuse_ocr(
    context: AppContext,
    episode: dict[str, Any],
    asr: list[AsrSegment],
    ocr_bars: list[OcrSegment] | None = None,
    ocr_band: tuple[float, float] | None = None,
    ocr_lines: list[tuple[float, float]] | None = None,
) -> tuple[
    list[AsrSegment],
    list[OcrSegment] | None,
    tuple[float, float] | None,
    list[tuple[float, float]] | None,
]:
    """硬字幕 OCR 通道 + 融合（analysis.ocr_enabled 默认开）。

    第三元是探测到的源字幕带、第四元是逐行框（覆盖数据链）：即便没融合出字幕条
    也要回传落库——带的位置是源片属性，与本轮台词抽取成败无关。
    """
    if context.settings.get("analysis.ocr_enabled", "1") != "1":
        return asr, None, ocr_band, ocr_lines
    if ocr_bars is None:
        extracted = _extract_bars(context, episode)
        if extracted is None:
            return asr, None, ocr_band, ocr_lines
        ocr_bars, ocr_band, ocr_lines = extracted
    if not ocr_bars:
        return asr, None, ocr_band, ocr_lines
    return fusion.fuse(asr, ocr_bars), ocr_bars, ocr_band, ocr_lines


def _cached_mining(
    context: AppContext, episode: dict[str, Any], *, ocr_enabled: bool
) -> tuple[list[OcrSegment], tuple[float, float], list[tuple[float, float]] | None] | None:
    """跨轮复用：源视频在分析后未变 + 已有字幕条产物 → 直接复用，不重挖。

    判据：视频 mtime ≤ analyzed_at（分析晚于素材改动）。ocr_channel 不参与——
    缓存的是 OCR 输出本身，通道开关只影响新鲜度与下次签名，不影响已有产物。
    """
    if not ocr_enabled:
        return None
    row = analysis_repo.get(context.conn, str(episode["id"]))
    if row is None or not row["ocr_segments"] or not row["subtitle_band"]:
        return None
    try:
        stat = Path(str(episode["source_path"])).stat()
    except OSError:
        return None
    if stat.st_mtime_ns > int(row["analyzed_at"]) * 1_000_000:
        return None
    try:
        bars = [OcrSegment.model_validate(b) for b in json.loads(row["ocr_segments"])]
        parsed = json.loads(row["subtitle_band"])
        # 两种落库格式都认：新 = {"band": [...], "lines": [[t,b],...]}；旧 = [t, b]
        if isinstance(parsed, dict):
            band = (float(parsed["band"][0]), float(parsed["band"][1]))
            lines = [(float(t), float(b)) for t, b in parsed.get("lines") or []]
        else:
            band = (float(parsed[0]), float(parsed[1]))
            lines = None
        return bars, band, lines or None
    except (ValueError, TypeError, KeyError):
        return None


def _extract_bars(
    context: AppContext, episode: dict[str, Any]
) -> tuple[
    list[OcrSegment] | None,
    tuple[float, float] | None,
    list[tuple[float, float]] | None,
]:
    """单集 OCR 抽取，返回 (字幕条, 源带, 行框)；失败返回 None 并留痕（不阻塞分析主链路）。

    字幕带与逐行框随字幕条一起回传（覆盖数据链）：调用方落库
    episode_analysis.subtitle_band，编码端 delogo 逐行擦除、烧录字幕带内压位。
    """
    duration = float(episode["duration"] or 0)
    if duration <= 0:
        return None, None, None
    try:
        return subtitle_ocr.extract_subtitles(
            Path(str(episode["source_path"])),
            context.work_dir / f"ocr_{episode['id']}",
            duration_s=duration,
        )
    except ImportError:
        return None, None, None  # rapidocr 未安装：ml extras 约定的纯 ASR 路径
    except Exception as exc:  # noqa: BLE001 - OCR 失败不影响分析主链路
        context.notifier.log("warn", f"OCR 字幕通道失败（不影响分析）: {exc}")
        return None, None, None


def _mine_hotwords(
    context: AppContext,
    targets: list[dict[str, Any]],
    cancel_event: threading.Event,
    on_episode: Callable[[int, int], None] | None = None,
    *,
    ocr_enabled: bool = True,
) -> tuple[
    dict[str, list[OcrSegment]],
    dict[str, tuple[float, float]],
    dict[str, list[tuple[float, float]]],
    str,
]:
    """阶段 A：全剧 OCR 抽取（落库）→ 挖掘全剧热词表；字幕带与逐行框按集回传。"""
    bars_by_episode: dict[str, list[OcrSegment]] = {}
    bands_by_episode: dict[str, tuple[float, float]] = {}
    lines_by_episode: dict[str, list[tuple[float, float]]] = {}
    if context.settings.get("analysis.ocr_enabled", "1") != "1":
        return bars_by_episode, bands_by_episode, lines_by_episode, ""
    for index, episode in enumerate(targets):
        if cancel_event.is_set():
            break
        episode_id = str(episode["id"])
        cached = _cached_mining(context, episode, ocr_enabled=ocr_enabled)
        bars, band, lines = cached if cached is not None else _extract_bars(context, episode)
        if on_episode is not None:
            on_episode(index + 1, len(targets))
        if band is not None:
            # 带是源片属性：即使本集没抽出字幕条（bars 为空）也记下来，逐集分析时落库
            bands_by_episode[episode_id] = band
            if lines:
                lines_by_episode[episode_id] = lines
        if not bars:
            continue
        bars_by_episode[episode_id] = bars
        analysis_repo.update_ocr_segments(
            context.conn, episode_id, json.dumps([b.model_dump() for b in bars])
        )
    hotwords = hotwords_engine.mine([b for bars in bars_by_episode.values() for b in bars])
    if hotwords:
        context.notifier.log("info", f"全剧热词表：{hotwords}")
    return bars_by_episode, bands_by_episode, lines_by_episode, hotwords
