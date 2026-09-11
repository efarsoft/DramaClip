"""narration 命名空间：编排/出片任务（generate_plans、produce）与风格清单。

任务级上下文（项目名、题材、跨集转写、口味层风格）统一在 `_inject_run_settings` 装配一次。
"""

from __future__ import annotations

import json
import threading
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.api.export import ExportRun, render_export
from dramaclip.engines.narration import copywriter, script_driver, scriptwriter
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

# 与 TTS 合成并行的两组：剧情解说已由 LLM 剧本驱动，每段都要配音，不再属"无 TTS"。
_NO_TTS_MODES = frozenset({"raw_clip", "subtitle_flow"})

# 会产出旁白槽位、因而读 `settings["_style_directives"]` 的模式（copywriter /
# scriptwriter 两侧都只往解说槽位里塞风格指令）。派生自上面两个集合，绝不另立
# 第四份手抄模式清单——纯剪辑作业连口味层的答案都无人可读，不该为它付选题往返。
_NARRATION_MODES = frozenset(SUPPORTED_MODES) - _NO_TTS_MODES


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
        done_episodes,
        modes,
        cancel_event,
    )
    return {"job_id": job_id}


def list_plans(context: AppContext, params: dict[str, Any]) -> list[dict[str, Any]]:
    return plans_repo.list_by_project(context.conn, str(params.get("project_id", "")))


def list_styles(context: AppContext, _params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return styles_lib.list_styles()


def _inject_run_settings(
    context: AppContext,
    settings: dict[str, str],
    episodes: list[dict[str, Any]],
    modes: list[str],
) -> list[dict[str, Any]]:
    """任务级一次性注入：项目名、题材、跨集转写、口味层风格。返回跨集输入。

    风格指令只有会产出旁白槽位的模式才读得到，故按 `modes` 设闸：纯剪辑作业
    一次选题都不付。转写只是 **AI 自选**风格的原料——用户钉死了风格就没有自选
    这回事，没有转写也照样要把用户选的风格注进去（否则既丢风格又丢那句留痕）。
    """
    project_id = str(episodes[0]["project_id"])
    project = projects_repo.get(context.conn, project_id)
    if project is None:
        raise ValueError(f"项目不存在: {project_id}")
    settings["_project_name"] = str(project["name"])
    record = analysis_repo.get(context.conn, str(episodes[0]["id"]))
    if record is not None and record["genre"]:
        settings["_genre"] = str(record["genre"])
    episode_inputs = _collect_episode_inputs(context, episodes)
    preferred = settings.get("narration.style_id")
    pinned = bool(preferred) and preferred != styles_lib.AUTO_STYLE_ID
    if any(mode in _NARRATION_MODES for mode in modes) and (episode_inputs or pinned):
        settings["_style_directives"] = str(
            script_driver.resolve_run_style(
                settings, episode_inputs, log=context.notifier.log
            ).get("directives", "")
        )
    return episode_inputs


def _run_generation_parallel(
    context: AppContext,
    job_id: str,
    episodes: list[dict[str, Any]],
    modes: list[str],
    cancel_event: threading.Event,
) -> None:
    """一键全部生成（原案 6.12）：无 TTS 模式与 TTS 模式两组并行，单模式失败不中断。"""
    context.job_store.mark_running(job_id)
    settings = dict(context.settings)
    try:
        episode_inputs = _inject_run_settings(context, settings, episodes, modes)
    except Exception as exc:  # noqa: BLE001 - 任务级装配失败必须落进 jobs 表，不能留 running
        context.job_store.mark_failed(job_id, str(exc))
        context.notifier.log("error", f"任务上下文装配失败: {exc}")
        context.cancel_events.pop(job_id, None)
        return

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
            label = narration_pipeline.MODE_LABELS.get(mode, mode)
            try:
                _generate_one(context, mode, episodes, episode_inputs, dict(settings))
            except Exception as exc:
                failures.append(f"{label}: {exc}")
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


def _generate_one(
    context: AppContext,
    mode: str,
    episodes: list[dict[str, Any]],
    episode_inputs: list[dict[str, Any]],
    settings: dict[str, str],
) -> None:
    """生成单模式编排：剧情解说走跨集剧本，其余模式走规则编排 + 逐槽文案。"""
    project_id = str(episodes[0]["project_id"])
    plan: PlanData | None = None
    used_ids = [str(episodes[0]["id"])]

    if mode == "dialogue_narration":
        if not episode_inputs:
            raise ValueError("没有带转写的已完成集，无法生成解说剧本")
        context.notifier.log(
            "info",
            f"跨集输入：{len(episode_inputs)} 集 → "
            f"每集约 {scriptwriter.transcript_sampling_quota(len(episode_inputs))} 段摘录",
        )
        scripted = script_driver.script_dialogue_plan(
            episode_inputs,
            settings,
            log=context.notifier.log,
            trace_dir=context.data_dir / "logs" / "llm",
        )
        if scripted is not None:
            plan, used_ids = scripted

    if plan is None:
        episode = episodes[0]
        episode_id = str(episode["id"])
        used_ids = [episode_id]
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
        if plan.narration_texts:
            plan = copywriter.write_plan_copy(
                plan,
                asr_segments,
                settings,
                mode_label=narration_pipeline.MODE_LABELS.get(mode, mode),
                trace_dir=context.data_dir / "logs" / "llm",
            )

    if plan.narration_texts:
        tts_dir = context.work_dir / "tts"
        models_dir = context.data_dir / "models"
        plan = narration_pipeline.synthesize_narration_texts(plan, settings, tts_dir, models_dir)
    plans_repo.create(
        context.conn,
        project_id,
        mode,
        used_ids,
        plan.model_dump(),
    )


def _collect_episode_inputs(
    context: AppContext,
    episodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """收集全部完成集的转写输入（跨集剧本原料），按集号升序。"""
    inputs: list[dict[str, Any]] = []
    for episode in sorted(episodes, key=lambda ep: int(ep["episode_number"])):
        record = analysis_repo.get(context.conn, str(episode["id"]))
        if record is None:
            continue
        segments = narration_pipeline.parse_asr_segments(record["asr_segments"])
        if not segments:
            continue
        inputs.append(
            {
                "number": int(episode["episode_number"]),
                "episode_id": str(episode["id"]),
                "duration": float(episode.get("duration") or 0.0),
                "segments": [
                    {"start": seg.start, "end": seg.end, "text": seg.text}
                    for seg in segments
                ],
            }
        )
    return inputs


def _parse_conflicts(raw: str | None) -> list[ConflictScore]:
    return [ConflictScore.model_validate(item) for item in json.loads(raw or "[]")]


def _parse_highlights(raw: str | None) -> list[HighlightSegment]:
    return [HighlightSegment.model_validate(item) for item in json.loads(raw or "[]")]


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
    settings = dict(context.settings)
    try:
        episode_inputs = _inject_run_settings(context, settings, episodes, modes)
    except Exception as exc:  # noqa: BLE001 - 任务级装配失败必须落进 jobs 表，不能留 running
        context.job_store.mark_failed(job_id, str(exc))
        context.notifier.log("error", f"任务上下文装配失败: {exc}")
        context.cancel_events.pop(job_id, None)
        return

    total = len(modes)
    failures: list[str] = []
    for index, mode in enumerate(modes):
        if cancel_event.is_set():
            context.job_store.mark_cancelled(job_id)
            context.cancel_events.pop(job_id, None)
            return
        base = index / total * 100
        label = narration_pipeline.MODE_LABELS.get(mode, mode)

        def report(percent: float, message: str, _base: float = base) -> None:
            context.job_store.set_progress(job_id, round(_base + percent / total, 1), message)
            context.notifier.progress(job_id, round(_base + percent / total, 1), message)

        context.notifier.progress(job_id, round(base, 1), f"({index + 1}/{total}) 生成{label}编排")
        try:
            _generate_one(context, mode, episodes, episode_inputs, dict(settings))
            plan_row = _newest_ready_plan(context, project_id, mode)
            if plan_row is None:
                raise ValueError("编排结果缺失")
            plan_data = PlanData.model_validate(plan_row["plan_data"])
            export_id = exports_repo.create(
                context.conn, project_id, str(plan_row["id"]), mode
            )
            report(30, f"渲染{label}成片")

            def scale_report(percent: float, message: str) -> None:
                """渲染进度 0-100 映射到本轮模式的 30~100 区间（编排占前 30）。"""
                report(30 + percent * 0.7, message)

            render_export(
                context,
                ExportRun(
                    export_id=export_id,
                    project_id=project_id,
                    plan_row=plan_row,
                    plan_data=plan_data,
                    cancel_event=cancel_event,
                ),
                report=scale_report,
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
