"""narration 命名空间：generate_plans（job）/ list_plans。"""

from __future__ import annotations

import json
import threading
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.api.export import render_export
from dramaclip.engines.narration import pipeline as narration_pipeline
from dramaclip.engines.narration import styles as styles_lib
from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.semantic.models import ConflictScore, HighlightSegment
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import exports as exports_repo
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
    "subtitle_flow",
    "dual_host_chat",
    "inner_monologue",
)

# 无 TTS 模式可与 TTS 合成并行（原案 6.12）
_NO_TTS_MODES = frozenset({"raw_clip", "dialogue_narration", "subtitle_flow"})


def register(router: Router, context: AppContext) -> None:
    router.register("narration.generate_plans", lambda params: generate_plans(context, params))
    router.register("narration.list_plans", lambda params: list_plans(context, params))
    router.register("narration.produce", lambda params: produce(context, params))
    router.register("narration.list_styles", lambda _params: list_styles(context))


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
        _run_generation_parallel,
        context,
        job_id,
        project_id,
        done_episodes,
        modes,
        cancel_event,
    )
    return {"job_id": job_id}


def list_plans(context: AppContext, params: dict[str, Any]) -> list[dict[str, Any]]:
    return plans_repo.list_by_project(context.conn, str(params.get("project_id", "")))


def list_styles(context: AppContext, _params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return styles_lib.list_styles()


def _run_generation_parallel(
    context: AppContext,
    job_id: str,
    project_id: str,
    episodes: list[dict[str, Any]],
    modes: list[str],
    cancel_event: threading.Event,
) -> None:
    """一键全部生成（原案 6.12）：无 TTS 模式与 TTS 模式两组并行，单模式失败不中断。"""
    context.job_store.mark_running(job_id)
    project = projects_repo.get(context.conn, project_id)
    if project is None:
        raise ValueError("项目不存在")
    settings = dict(context.settings)
    settings["_project_name"] = str(project["name"])
    analysis_record = analysis_repo.get(context.conn, str(episodes[0]["id"]))
    if analysis_record is not None and analysis_record["genre"]:
        settings["_genre"] = str(analysis_record["genre"])

    tts_modes = [mode for mode in modes if mode not in _NO_TTS_MODES]
    fast_modes = [mode for mode in modes if mode in _NO_TTS_MODES]
    total = len(modes)
    done_count = 0
    lock = threading.Lock()
    failures: list[str] = []

    def run_group(group_modes: list[str]) -> None:
        nonlocal done_count
        for mode in group_modes:
            if cancel_event.is_set():
                return
            try:
                _generate_one(context, mode, episodes, dict(settings))
            except Exception as exc:
                failures.append(f"{_mode_label(mode)}: {exc}")
            with lock:
                done_count += 1
                context.job_store.set_progress(job_id, round(done_count / total * 100, 1))

    threads = [
        threading.Thread(
            target=run_group,
            args=(group,),
            name=f"gen-{'tts' if group is tts_modes else 'fast'}",
        )
        for group in (tts_modes, fast_modes)
        if group
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    if cancel_event.is_set():
        context.job_store.mark_cancelled(job_id)
    elif failures:
        context.job_store.mark_failed(job_id, "; ".join(failures))
        context.notifier.log("error", f"部分编排失败: {'; '.join(failures)}")
    else:
        context.job_store.mark_completed(job_id)
    context.cancel_events.pop(job_id, None)


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
    tts_modes = (
        "intro_narration",
        "cross_narration",
        "ultra_short_hook",
        "full_narration",
        "dual_host_chat",
        "inner_monologue",
    )
    if mode in tts_modes:
        tts_dir = context.work_dir / "tts"
        models_dir = context.work_dir.parent.parent / "models"
        plan = narration_pipeline.synthesize_narration_texts(plan, settings, tts_dir, models_dir)
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



def produce(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """组合任务：逐模式 编排(文案/配音) → 自动渲染成片；出片记录随产随记。"""
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

    job_id = context.job_store.create("produce", ref_id=project_id)
    cancel_event = threading.Event()
    context.cancel_events[job_id] = cancel_event
    context.executor.submit(
        _run_produce, context, job_id, project_id, done_episodes, modes, cancel_event
    )
    return {"job_id": job_id}


def _run_produce(
    context: AppContext,
    job_id: str,
    project_id: str,
    episodes: list[dict[str, Any]],
    modes: list[str],
    cancel_event: threading.Event,
) -> None:
    """逐模式：编排(文案/配音) → 渲染成片；单模式失败不中断其余。"""
    context.job_store.mark_running(job_id)
    project = projects_repo.get(context.conn, project_id)
    settings = dict(context.settings)
    if project is not None:
        settings["_project_name"] = str(project["name"])
    analysis_record = analysis_repo.get(context.conn, str(episodes[0]["id"]))
    if analysis_record is not None and analysis_record["genre"]:
        settings["_genre"] = str(analysis_record["genre"])

    total = len(modes)
    failures: list[str] = []
    for index, mode in enumerate(modes):
        if cancel_event.is_set():
            context.job_store.mark_cancelled(job_id)
            context.cancel_events.pop(job_id, None)
            return
        base = index / total * 100
        label = _mode_label(mode)

        def report(percent: float, message: str, _base: float = base) -> None:
            context.job_store.set_progress(job_id, round(_base + percent / total, 1))
            context.notifier.progress(job_id, round(_base + percent / total, 1), message)

        context.notifier.progress(job_id, round(base, 1), f"({index + 1}/{total}) 生成{label}编排")
        try:
            _generate_one(context, mode, episodes, dict(settings))
            plan_row = _newest_ready_plan(context, project_id, mode)
            if plan_row is None:
                raise ValueError("编排结果缺失")
            plan_data = PlanData.model_validate(plan_row["plan_data"])
            export_id = exports_repo.create(
                context.conn, project_id, str(plan_row["id"]), mode
            )
            report(30, f"渲染{label}成片")
            render_export(
                context,
                export_id,
                project_id,
                plan_row,
                plan_data,
                cancel_event=cancel_event,
                report=lambda p, m, _r=report, _b=base: _r(30 + p * 0.7, m),
            )
        except Exception as exc:
            failures.append(f"{label}: {exc}")
            context.notifier.log("error", f"{label} 出片失败: {exc}")

    if cancel_event.is_set():
        context.job_store.mark_cancelled(job_id)
    elif failures:
        context.job_store.mark_failed(job_id, "; ".join(failures))
    else:
        context.job_store.set_progress(job_id, 100.0)
        context.job_store.mark_completed(job_id)
    context.cancel_events.pop(job_id, None)


def _newest_ready_plan(context: AppContext, project_id: str, mode: str) -> dict[str, Any] | None:
    plans = [
        plan
        for plan in plans_repo.list_by_project(context.conn, project_id)
        if plan["narration_mode"] == mode and plan["status"] == "ready"
    ]
    plans.sort(key=lambda plan: plan["created_at"], reverse=True)
    return plans[0] if plans else None
