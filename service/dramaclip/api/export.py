"""export 命名空间：start（job）/ list。"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.engines.exporter import encoder
from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.subtitle import presets as subtitle_presets
from dramaclip.engines.subtitle.ass_generator import build_ass
from dramaclip.infra.ffmpeg import probe
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.rpc import Router, RpcDomainError

_ERR_PLAN_NOT_FOUND = -32401

# 纯原片模式零加工：不遮罩（原案 6B）
_NO_MASK_MODES = {"raw_clip"}


def _safe_filename(name: str) -> str:
    """项目名 → 安全文件名段（去除路径/非法字符）。"""
    forbidden = "\\/:*?\"<>|"
    cleaned = "".join(ch for ch in name.strip() if ch not in forbidden)
    return cleaned.replace(" ", "_")[:40] or "project"


def register(router: Router, context: AppContext) -> None:
    router.register("export.start", lambda params: start(context, params))
    router.register("export.list", lambda params: list_exports(context, params))
    router.register("export.list_works", lambda params: list_works(context, params))


def start(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
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
    job_id = context.job_store.create("export", ref_id=export_id)
    cancel_event = threading.Event()
    context.cancel_events[job_id] = cancel_event
    context.executor.submit(
        _run_export, context, job_id, export_id, project_id, plan_row, plan_data, cancel_event
    )
    return {"job_id": job_id, "export_id": export_id}


def list_exports(context: AppContext, params: dict[str, Any]) -> list[dict[str, Any]]:
    return exports_repo.list_by_project(context.conn, str(params.get("project_id", "")))


def list_works(context: AppContext, params: dict[str, Any]) -> list[dict[str, Any]]:
    """作品库：跨项目已完成成片（附项目名），limit 可调。"""
    limit = int(params.get("limit", 60))
    return exports_repo.list_completed_works(context.conn, limit=limit)


def render_export(
    context: AppContext,
    export_id: str,
    project_id: str,
    plan_row: dict[str, Any],
    plan_data: PlanData,
    *,
    cancel_event: threading.Event,
    report: Any,
) -> Path:
    """渲染核心：剪辑→遮罩→字幕→编码→写成品记录（失败抛异常，不管理 job）。"""
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
    tts_segments = {
        index: Path(text.audio_path)
        for index, text in enumerate(plan_data.narration_texts)
        if text.audio_path is not None
    }
    mask = plan_row["narration_mode"] not in _NO_MASK_MODES
    preset = subtitle_presets.get_preset(plan_row.get("subtitle_preset"))

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


def _run_export(
    context: AppContext,
    job_id: str,
    export_id: str,
    project_id: str,
    plan_row: dict[str, Any],
    plan_data: PlanData,
    cancel_event: threading.Event,
) -> None:
    context.job_store.mark_running(job_id)

    def report(percent: float, message: str) -> None:
        context.job_store.set_progress(job_id, round(percent, 1))
        context.notifier.progress(job_id, round(percent, 1), message)
        exports_repo.set_progress(context.conn, export_id, round(percent, 1))

    try:
        out_path = render_export(
            context,
            export_id,
            project_id,
            plan_row,
            plan_data,
            cancel_event=cancel_event,
            report=report,
        )
        context.job_store.mark_completed(job_id)
        context.notifier.log("info", f"导出完成: {out_path.name}")
    except Exception as exc:
        exports_repo.mark_failed(context.conn, export_id, str(exc))
        context.job_store.mark_failed(job_id, str(exc))
        context.notifier.log("error", f"导出失败: {exc}")
