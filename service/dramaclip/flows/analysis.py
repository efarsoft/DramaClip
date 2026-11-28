"""analysis 投递体族：预筛/分析/语义重对齐三个作业体 + 并发闸。

runner 外溢第一刀自 api/analysis.py 下沉（2026-11-28，照 flows/plan_runner 同款
模式）：api 侧保留同名 re-import，RPC 调用点与 `monkeypatch.setattr(analysis_api,
...)` 形态的打桩读者不迁移；模块对象级补丁（setattr(analysis_job, ...)）随
模块本体迁 flows 后须打 flows 侧。

_run_prescreen 的 then_analyze 移交走 api 注入的闭包（start 本体在 api，flows
不反向 import）——作业体与 RPC 入口解耦，闸位校验照旧走同一条 start 路径。
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dramaclip.api.context import AppContext, llm_trace_dir
from dramaclip.engines.analysis import prescreen as prescreen_engine
from dramaclip.engines.analysis.models import (
    AsrSegment,
    AudioFeatures,
    EpisodeRawAnalysis,
    SceneInfo,
)
from dramaclip.engines.semantic import pipeline as semantic_pipeline
from dramaclip.flows.analysis_job import _current_signature, _run_job
from dramaclip.infra import config
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import prescreen as prescreen_repo

# 全局分析并发闸：同时最多 2 个分析任务（多项目并发时防 GIL/CPU 争抢）
_analysis_semaphore = threading.Semaphore(2)


def _run_prescreen(
    context: AppContext,
    job_id: str,
    project_id: str,
    targets: list[dict[str, Any]],
    cancel_event: threading.Event,
    then_analyze: bool = False,
    handoff: Callable[[list[str]], None] | None = None,
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
    if then_analyze and handoff is not None:
        try:
            recommended_ids = [
                str(episode["id"])
                for episode in targets
                if _prescreen_recommended(context, str(episode["id"]))
            ]
            if recommended_ids:
                handoff(recommended_ids)
        except Exception as exc:  # noqa: BLE001 - 移交失败如实留痕，不连坐已完成的预筛
            context.notifier.log("error", f"预筛完成但自动分析未启动: {exc}")


def _prescreen_recommended(context: AppContext, episode_id: str) -> bool:
    row = prescreen_repo.get(context.conn, episode_id)
    return bool(row and row.get("recommended"))


def _run_analysis_gated(
    context: AppContext,
    job_id: str,
    project_id: str,
    targets: list[dict[str, Any]],
    cancel_event: threading.Event,
    resume_strict: bool = False,
) -> None:
    """semaphore 包装：分析完成后释放并发闸。

    第 6 个位置参数由 `start` 按「是否点名选集」给出（`tracked` 只收 fn + *args）。

    直接作为 `notifier.tracked` 的任务体（而非返回一个待调用的闭包）：
    `tracked` 的契约是 `fn(*args)` 一步执行完，经它投递的任务必须自己跑完，
    不能在返回值里再藏一层——76600ce 把 `tracked` 从「收无参 lambda」改成
    「收 fn + *args」后，旧写法 `lambda: _analysis_gate_wrap(...)` 会因多传
    一个 job_id 直接 TypeError，分析任务在启动瞬间就崩（40 条测试转红）。
    """
    try:
        _run_job(context, job_id, project_id, targets, cancel_event, resume_strict=resume_strict)
    finally:
        _analysis_semaphore.release()


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
