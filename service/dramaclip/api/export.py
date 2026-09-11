"""export 命名空间：start / retry（均为 job）/ list / list_works。"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.engines.analysis.models import SpeechZone
from dramaclip.engines.exporter import encoder
from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.subtitle import presets as subtitle_presets
from dramaclip.engines.subtitle.ass_generator import build_ass
from dramaclip.infra import config
from dramaclip.infra.ffmpeg import probe
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.rpc import Router, RpcDomainError

_ERR_PLAN_NOT_FOUND = -32401
_ERR_EXPORT_NOT_FOUND = -32404
_ERR_EXPORT_NOT_RETRYABLE = -32405  # 导出域 -32400~-32499（见 common.json x-error-codes）

# 纯原片模式零加工：不遮罩（原案 6B）
_NO_MASK_MODES = {"raw_clip"}


def _safe_filename(name: str) -> str:
    """项目名 → 安全文件名段（去除路径/非法字符）。"""
    forbidden = "\\/:*?\"<>|"
    cleaned = "".join(ch for ch in name.strip() if ch not in forbidden)
    return cleaned.replace(" ", "_")[:40] or "project"


def register(router: Router, context: AppContext) -> None:
    router.register("export.start", lambda params: start(context, params))
    router.register("export.retry", lambda params: retry(context, params))
    router.register("export.list", lambda params: list_exports(context, params))
    router.register("export.list_works", lambda params: list_works(context, params))


@dataclass(frozen=True)
class ExportRun:
    """一次导出渲染的不变输入（export_id 之外全部只读，渲染期间不会改写）。

    收成对象前这些值以位置参数在 start/retry/produce → _run_export → render_export
    链路上传递，`export_id` 与 `project_id` 同为 str 且相邻——传颠倒不会报错，
    只会把成片渲染进另一个项目。三处调用点共用一个名字即是收益。
    不含 job_id：produce 路径复用 render_export 时那个 job 是 produce job，不是 export job。
    """

    export_id: str
    project_id: str
    plan_row: dict[str, Any]
    plan_data: PlanData
    cancel_event: threading.Event


def _submit_export(
    context: AppContext,
    *,
    export_id: str,
    project_id: str,
    plan_row: dict[str, Any],
    plan_data: PlanData,
) -> str:
    """建 export 任务 → 注册取消事件 → 投递执行池，返回 job_id。

    start 与 retry 曾各写一遍这四步；取消事件的注册与 _run_export finally 里的回收
    必须成对，两处各写时漏掉一半就留下 cancel_events 无界增长。
    """
    job_id = context.job_store.create("export", ref_id=export_id)
    cancel_event = threading.Event()
    context.cancel_events[job_id] = cancel_event
    context.executor.submit(
        _run_export,
        context,
        job_id,
        ExportRun(
            export_id=export_id,
            project_id=project_id,
            plan_row=plan_row,
            plan_data=plan_data,
            cancel_event=cancel_event,
        ),
    )
    return job_id


def start(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """新建一次导出：建记录后投递渲染任务（渲染本身异步，进度走 jobs）。"""
    plan_id = str(params.get("plan_id", ""))
    plan_row = plans_repo.get(context.conn, plan_id)
    if plan_row is None:
        raise RpcDomainError(_ERR_PLAN_NOT_FOUND, f"编排方案不存在: {plan_id}")
    plan_data = PlanData.model_validate(plan_row["plan_data"])
    if not plan_data.timeline:
        raise RpcDomainError(_ERR_PLAN_NOT_FOUND, "编排时间轴为空")

    project_id = str(plan_row["project_id"])
    export_id = exports_repo.create(
        conn=context.conn,
        project_id=project_id,
        plan_id=plan_id,
        narration_mode=str(plan_row["narration_mode"]),
    )
    job_id = _submit_export(
        context,
        export_id=export_id,
        project_id=project_id,
        plan_row=plan_row,
        plan_data=plan_data,
    )
    return {"job_id": job_id, "export_id": export_id}


def retry(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """重试一条失败导出：**复用原 export_id 覆盖写**，不新建记录。"""
    export_id = str(params.get("export_id", ""))
    record = exports_repo.get(context.conn, export_id)
    if record is None:
        raise RpcDomainError(_ERR_EXPORT_NOT_FOUND, f"导出记录不存在: {export_id}")
    if record["status"] != "failed":
        raise RpcDomainError(
            _ERR_EXPORT_NOT_RETRYABLE, f"仅失败记录可重试，当前 {record['status']}"
        )
    plan_id = str(record["narration_plan_id"])
    plan_row = plans_repo.get(context.conn, plan_id)
    if plan_row is None:
        raise RpcDomainError(_ERR_PLAN_NOT_FOUND, f"编排方案不存在: {plan_id}")
    plan_data = PlanData.model_validate(plan_row["plan_data"])
    # 复位是 CAS（仅当仍为 failed 才生效）：并发点两次重试时只有一个能复位成功，
    # 另一个在此被判不可重试，避免双双渲染进同一产物路径。
    if not exports_repo.reset_for_retry(context.conn, export_id):
        raise RpcDomainError(_ERR_EXPORT_NOT_RETRYABLE, "该导出已被其他请求抢先重试")
    job_id = _submit_export(
        context,
        export_id=export_id,
        project_id=str(record["project_id"]),
        plan_row=plan_row,
        plan_data=plan_data,
    )
    return {"job_id": job_id, "export_id": export_id}


def list_exports(context: AppContext, params: dict[str, Any]) -> list[dict[str, Any]]:
    return exports_repo.list_by_project(context.conn, str(params.get("project_id", "")))


def list_works(context: AppContext, params: dict[str, Any]) -> list[dict[str, Any]]:
    """作品库：跨项目已完成成片（附项目名），limit 可调。"""
    limit = int(params.get("limit", 60))
    return exports_repo.list_completed_works(context.conn, limit=limit)


def tts_audio_by_segment(plan: PlanData) -> dict[int, str]:
    """段序号 → 旁白音频路径。按 segment.narration_id 显式取用，绝不按位置推断。

    位置推断在两条路上都会静默错音：`ducked`（全片解说每段都是）从来不算 narration 段，
    整片旁白因此丢失；TTS 失败被 `kept_texts` 过滤后，「第 N 条 narration 段」与
    「第 N 条文案」也不再同号。id 缺失或对不上号的段就是没有旁白，直接不给条目。
    """
    by_id = {
        text.id: text.audio_path for text in plan.narration_texts if text.audio_path is not None
    }
    return {
        index: by_id[segment.narration_id]
        for index, segment in enumerate(plan.timeline)
        if segment.narration_id is not None and segment.narration_id in by_id
    }


def _output_size(settings: config.Settings) -> tuple[int, int]:
    """输出分辨率：读设置键 export.width/height（默认值源在 infra.config），偶数化并钳制最小 480。

    走 config.get_int 而非本地字面量兜底：本文件不得再抄一份 1080/1920（docs/04 §5.2），
    且该函数对缺失与非法值统一回退默认，不像 int(settings.get(...)) 那样被脏值炸穿。
    """
    width = max(config.get_int(settings, "export.width"), 480)
    height = max(config.get_int(settings, "export.height"), 480)
    return width - width % 2, height - height % 2


def render_export(
    context: AppContext,
    run: ExportRun,
    *,
    report: Callable[[float, str], None],
) -> Path:
    """渲染核心：剪辑→遮罩→字幕→编码→写成品记录（失败抛异常，不管理 job）。

    入参收成 ExportRun 后本函数不再关心 job 与取消事件的注册，只按 run 渲染。
    """
    export_id = run.export_id
    project_id = run.project_id
    plan_row = run.plan_row
    plan_data = run.plan_data
    cancel_event = run.cancel_event

    output_root = context.data_dir / "outputs" / project_id
    output_root.mkdir(parents=True, exist_ok=True)
    project = projects_repo.get(context.conn, project_id)
    project_name = str(project["name"]) if project else project_id[:8]
    safe_name = _safe_filename(project_name)
    out_path = output_root / f"{safe_name}_{plan_row['narration_mode']}_{export_id[:6]}.mp4"

    episode_paths = {
        str(ep["id"]): str(ep["source_path"])
        for ep in episodes_repo.list_by_project(context.conn, project_id)
    }
    # 台词保护区的库内兜底源：分析层 asr_segments 按集预取一次。
    # 优先级在编码器里判：源视频同名 .srt（人工校对过的手工字幕）优先，
    # 该文件不存在时才回退用这里预取的 ASR 区（见 encoder.export_plan 的 zones_cache）
    dialogue_zones: dict[str, list[SpeechZone]] = {}
    for segment in plan_data.timeline:
        episode_id = segment.episode_id
        if episode_id in dialogue_zones:
            continue
        record = analysis_repo.get(context.conn, episode_id)
        if record is None or not record["asr_segments"]:
            continue
        zones = [
            SpeechZone(start=float(item["start"]), end=float(item["end"]))
            for item in json.loads(record["asr_segments"])
            if float(item.get("end", 0)) > float(item.get("start", 0))
        ]
        if zones:
            dialogue_zones[episode_id] = zones

    tts_segments = tts_audio_by_segment(plan_data)
    mask = plan_row["narration_mode"] not in _NO_MASK_MODES
    preset = subtitle_presets.get_preset(context.settings.get("subtitle.default_preset"))
    out_size = _output_size(context.settings)

    def burn_subtitle(segment_index: int, text: str, duration_s: float) -> str:
        """生成段级 ass 文件并返回路径（相对时间轴 0→duration）。"""
        ass_dir = context.work_dir / "export" / export_id
        ass_dir.mkdir(parents=True, exist_ok=True)
        ass_path = ass_dir / f"seg_{segment_index:03d}.ass"
        ass_path.write_text(
            build_ass([{"start": 0.0, "end": duration_s, "text": text}], preset),
            encoding="utf-8",
        )
        return str(ass_path)

    encoder.export_plan(
        plan_data,
        episode_paths,
        out_path,
        context.work_dir / "export" / export_id,
        tts_audio_by_segment=tts_segments or None,
        mask=mask,
        cancel=cancel_event,
        on_progress=report,
        subtitle_burner=burn_subtitle if plan_data.mode != "raw_clip" else None,
        dialogue_zones=dialogue_zones,
        out_size=out_size,
    )
    exports_repo.mark_completed(context.conn, export_id, str(out_path))
    try:
        media = probe.probe(out_path)
        exports_repo.set_meta(
            context.conn, export_id, duration_s=media.duration_s, size_bytes=out_path.stat().st_size
        )
    except (ValueError, OSError):
        pass  # 元信息回填失败不影响导出成功
    return out_path


def _run_export(context: AppContext, job_id: str, run: ExportRun) -> None:
    """执行池入口：把一次 ExportRun 跑成 jobs 表里的一条终态记录。

    进度双写（jobs + export_jobs）是有意的：前者给队列页、后者给出片记录页。
    渲染失败只记不抛——异常已写进两条记录，再抛给未来得及看的调用方没有意义。
    """
    context.job_store.mark_running(job_id)

    def report(percent: float, message: str) -> None:
        context.job_store.set_progress(job_id, round(percent, 1), message)
        context.notifier.progress(job_id, round(percent, 1), message)
        exports_repo.set_progress(context.conn, run.export_id, round(percent, 1))

    try:
        out_path = render_export(context, run, report=report)
        context.job_store.mark_completed(job_id)
        context.notifier.log("info", f"导出完成: {out_path.name}")
    except Exception as exc:
        exports_repo.mark_failed(context.conn, run.export_id, str(exc))
        context.job_store.mark_failed(job_id, str(exc))
        context.notifier.log("error", f"导出失败: {exc}")
    finally:
        # 与 analysis/narration/models 一致：注册的取消事件必须回收，否则字典无界增长
        context.cancel_events.pop(job_id, None)
