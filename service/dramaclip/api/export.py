"""export 命名空间：submit（按方案排队渲染）/ retry（幂等重跑）/ list / list_works。"""

from __future__ import annotations

import contextlib
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.engines.analysis.models import SpeechZone
from dramaclip.engines.exporter import encoder, loudness
from dramaclip.engines.narration.conversion import defects
from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.subtitle import presets as subtitle_presets
from dramaclip.engines.subtitle.ass_generator import build_ass, line_char_cap, split_subtitle_text
from dramaclip.infra import config
from dramaclip.infra.ffmpeg import cover as ffmpeg_cover
from dramaclip.infra.ffmpeg import probe
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.rpc import Router, RpcDomainError

_ERR_PLAN_NOT_FOUND = -32401
_ERR_NO_PLANS = -32406
_ERR_PLAN_NOT_RENDERABLE = -32407
_ERR_EXPORT_NOT_FOUND = -32404
_ERR_EXPORT_NOT_RETRYABLE = -32405  # 导出域 -32400~-32499（见 common.json x-error-codes）

def _safe_filename(name: str) -> str:
    """项目名 → 安全文件名段（去除路径/非法字符）。"""
    forbidden = "\\/:*?\"<>|"
    cleaned = "".join(ch for ch in name.strip() if ch not in forbidden)
    return cleaned.replace(" ", "_")[:40] or "project"


def register(router: Router, context: AppContext) -> None:
    router.register("export.submit", lambda params: submit(context, params))
    router.register("export.retry", lambda params: retry(context, params))
    router.register("export.list", lambda params: list_exports(context, params))
    router.register("export.list_works", lambda params: list_works(context, params))
    router.register("export.get", lambda params: get_export(context, params))
    router.register("export.ensure_covers", lambda params: ensure_covers(context, params))


@dataclass(frozen=True)
class ExportRun:
    """一次导出渲染的不变输入（export_id 之外全部只读，渲染期间不会改写）。
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
    """
    job_id = context.job_store.create("export", ref_id=export_id)
    cancel_event = threading.Event()
    context.cancel_events[job_id] = cancel_event
    context.executor.submit(
        context.notifier.tracked(
            job_id,
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
    )
    return job_id


def submit(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """阶段4：把已规划好的方案排队渲染。规划与渲染就此分开。一条方案一个 export job；
    同一次调用里重复的 plan_id 只出一次片；坏的逐条拒绝并给理由，好的一起走。"""
    raw = params.get("plan_ids")
    if not isinstance(raw, list) or not raw:
        raise RpcDomainError(_ERR_NO_PLANS, "plan_ids 必须是非空数组")
    plan_ids = list(dict.fromkeys(str(item) for item in raw))
    accepted: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    for plan_id in plan_ids:
        plan_row = plans_repo.get(context.conn, plan_id)
        if plan_row is None:
            rejected.append({"plan_id": plan_id, "reason": f"编排方案不存在: {plan_id}"})
            continue
        try:
            plan_data = PlanData.model_validate(plan_row["plan_data"])
            _assert_renderable(plan_row, plan_data)
        except RpcDomainError as exc:
            rejected.append({"plan_id": plan_id, "reason": exc.message})
            continue
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
        accepted.append({"plan_id": plan_id, "export_id": export_id, "job_id": job_id})
    return {"exports": accepted, "rejected": rejected}


def _assert_renderable(plan_row: dict[str, Any], plan_data: PlanData) -> None:
    """提交/重试前的可渲染性守卫：方案行必须是拿去就能渲的成品输入。
    """
    if plan_row["status"] != "ready":
        raise RpcDomainError(_ERR_PLAN_NOT_RENDERABLE, f"方案状态为 {plan_row['status']}，不可渲染")
    if not plan_data.timeline:
        raise RpcDomainError(_ERR_PLAN_NOT_RENDERABLE, "编排时间轴为空")
    voiced = {text.id: text for text in plan_data.narration_texts}
    for segment in plan_data.timeline:
        if segment.audio not in ("narration", "ducked"):
            continue
        slot = voiced.get(segment.narration_id or "")
        if slot is None or not str(slot.text or "").strip():
            raise RpcDomainError(
                _ERR_PLAN_NOT_RENDERABLE,
                f"旁白段 {segment.episode_id}@{segment.start} 没有解说文案",
            )
    for issue in defects(plan_data):
        raise RpcDomainError(_ERR_PLAN_NOT_RENDERABLE, issue)


def retry(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """重试一条失败导出：**复用原 export_id 覆盖写**，不新建记录。"""
    export_id = str(params.get("export_id", ""))
    record = exports_repo.get(context.conn, export_id)
    if record is None:
        raise RpcDomainError(_ERR_EXPORT_NOT_FOUND, f"导出记录不存在: {export_id}")
    # 可重试判据与 reset_for_retry 的 CAS 条件必须同为一个谓词，否则下面的 Python 检查
    # 与后面的 SQL 复位会各说各话、并发保护失效；故两边都读 exports_repo.STATUS_FAILED。
    if record["status"] != exports_repo.STATUS_FAILED:
        raise RpcDomainError(
            _ERR_EXPORT_NOT_RETRYABLE, f"仅失败记录可重试，当前 {record['status']}"
        )
    plan_id = str(record["narration_plan_id"])
    plan_row = plans_repo.get(context.conn, plan_id)
    if plan_row is None:
        raise RpcDomainError(_ERR_PLAN_NOT_FOUND, f"编排方案不存在: {plan_id}")
    # 守卫排在 CAS 复位之前：注定失败的重试不该把 failed 洗成 pending
    plan_data = PlanData.model_validate(plan_row["plan_data"])
    _assert_renderable(plan_row, plan_data)
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


def _extract_cover(context: AppContext, export_id: str, out_path: Path) -> None:
    """成品逐片钩帧：失败静默（封面缺失退化为占位图，不影响导出成功）。"""
    covers_dir = context.data_dir / "covers" / "exports"
    covers_dir.mkdir(parents=True, exist_ok=True)
    cover_path = covers_dir / f"{export_id}.jpg"
    if cover_path.is_file():
        return
    if ffmpeg_cover.extract_cover(out_path, cover_path):
        exports_repo.set_cover(context.conn, export_id, str(cover_path))


def ensure_covers(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """补拍历史成片的封面（幂等）：只处理已完成且 cover_path 为空的记录。"""
    limit = max(min(int(params.get("limit", 200)), 500), 1)
    generated = 0
    for row in exports_repo.list_missing_covers(context.conn, limit):
        out_path = Path(str(row["output_path"]))
        if not out_path.is_file():
            continue
        covers_dir = context.data_dir / "covers" / "exports"
        covers_dir.mkdir(parents=True, exist_ok=True)
        cover_path = covers_dir / f"{row['id']}.jpg"
        if ffmpeg_cover.extract_cover(out_path, cover_path):
            exports_repo.set_cover(context.conn, str(row["id"]), str(cover_path))
            generated += 1
    return {"ok": True, "generated": generated}


def get_export(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """单条导出记录（成片详情页数据源）。"""
    export_id = str(params.get("export_id", ""))
    row = exports_repo.get(context.conn, export_id)
    if row is None:
        raise RpcDomainError(_ERR_EXPORT_NOT_FOUND, f"导出记录不存在: {export_id}")
    return row


def list_works(context: AppContext, params: dict[str, Any]) -> list[dict[str, Any]]:
    """作品库：跨项目已完成成片（附项目名），limit 可调。"""
    limit = int(params.get("limit", 60))
    return exports_repo.list_completed_works(context.conn, limit=limit)


def tts_audio_by_segment(plan: PlanData) -> dict[int, str]:
    """段序号 → 旁白音频路径。按 segment.narration_id 显式取用，绝不按位置推断。
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
    """渲染核心：剪辑→字幕→编码→写成品记录（失败抛异常，不管理 job）。
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
    preset = subtitle_presets.get_preset(context.settings.get("subtitle.default_preset"))
    out_size = _output_size(context.settings)

    def burn_subtitle(segment_index: int, text: str, duration_s: float) -> str:
        """生成段级 ass 文件并返回路径（相对时间轴 0→duration）。

        长文案按标点/字数拆成多行字幕，时长按字数比例分配——整段一行会溢出画面。
        每行几个字的上限问预设要（`line_char_cap`）：字号 64 与字号 96 能塞进同一幅
        1080 宽的画框的字数不是一回事，写死一个数的话大字号预设会「拆了，但每条照样放
        不下」，真机烧出来整行向两侧溢出、首尾被画框切掉（实测）。
        """
        ass_dir = context.work_dir / "export" / export_id
        ass_dir.mkdir(parents=True, exist_ok=True)
        ass_path = ass_dir / f"seg_{segment_index:03d}.ass"
        chunks = split_subtitle_text(text, line_char_cap(preset))
        total_chars = sum(len(c) for c in chunks)
        emotion = None
        if 0 <= segment_index < len(plan_data.timeline):
            emotion = plan_data.timeline[segment_index].emotion_label
        lines: list[dict[str, Any]] = []
        cursor = 0.0
        for chunk in chunks:
            span = duration_s * len(chunk) / total_chars
            lines.append(
                {
                    "start": cursor,
                    "end": cursor + span,
                    "text": chunk,
                    "emotion_label": emotion,
                }
            )
            cursor += span
        ass_path.write_text(build_ass(lines, preset), encoding="utf-8")
        return str(ass_path)

    # 输出编码：auto=探测到 NVENC 可用即 GPU 编码（黑帧实编验证），失败/关闭回退 libx264
    codec_setting = str(context.settings.get("export.encoder", "auto") or "auto").lower()
    if codec_setting == "auto":
        video_codec = "h264_nvenc" if encoder.nvenc_available() else "libx264"
    else:
        video_codec = codec_setting
    encoder.export_plan(
        plan_data,
        episode_paths,
        out_path,
        context.work_dir / "export" / export_id,
        video_codec=video_codec,
        tts_audio_by_segment=tts_segments or None,
        cancel=cancel_event,
        on_progress=report,
        subtitle_burner=burn_subtitle if plan_data.mode != "raw_clip" else None,
        dialogue_zones=dialogue_zones,
        out_size=out_size,
        loudness_target=loudness.LoudnessTarget.from_settings(context.settings),
    )
    exports_repo.mark_completed(context.conn, export_id, str(out_path))
    try:
        media = probe.probe(out_path)
        exports_repo.set_meta(
            context.conn, export_id, duration_s=media.duration_s, size_bytes=out_path.stat().st_size
        )
    except (ValueError, OSError):
        pass  # 元信息回填失败不影响导出成功
    with contextlib.suppress(OSError, ValueError):
        _extract_cover(context, export_id, out_path)  # 封面失败不影响导出成功
    return out_path


def _needs_voice(plan: PlanData) -> bool:
    by_id = {text.id: text for text in plan.narration_texts}
    for segment in plan.timeline:
        if segment.audio not in ("narration", "ducked"):
            continue
        slot = by_id.get(segment.narration_id or "")
        path = None if slot is None else slot.audio_path
        if not path or not Path(str(path)).is_file():
            return True
    return False


def _ensure_voiced(context: AppContext, plan_row: dict[str, Any], plan_data: PlanData) -> PlanData:
    """勾选导出时才配音：规划阶段故意不合成。"""
    if not _needs_voice(plan_data):
        return plan_data
    from dramaclip.api import narration as narration_api

    project_id = str(plan_row["project_id"])
    durations = {
        str(episode["id"]): float(episode["duration"] or 0.0)
        for episode in episodes_repo.list_by_project(context.conn, project_id)
    }
    settings = narration_api._effective_settings(context, project_id)
    voiced = narration_api._voice(context, plan_data, settings, durations)
    plans_repo.update_plan_data(context.conn, str(plan_row["id"]), voiced.model_dump())
    if _needs_voice(voiced):
        raise ValueError("旁白音频合成失败，不能用原声顶替")
    return voiced


def _ensure_titles(context: AppContext, plan_row: dict[str, Any]) -> None:
    """成片落库时带 8 条标题；已有标题或 LLM 不可用都不挡导出。"""
    if plan_row.get("titles"):
        return
    from dramaclip.api import narration as narration_api

    with contextlib.suppress(Exception):
        narration_api.generate_titles(context, {"plan_id": str(plan_row["id"])})


def _run_export(context: AppContext, job_id: str, run: ExportRun) -> None:
    """执行池入口：把一次 ExportRun 跑成 jobs 表里的一条终态记录。
    """
    context.job_store.mark_running(job_id)

    def report(percent: float, message: str) -> None:
        context.job_store.set_progress(job_id, round(percent, 1), message)
        context.notifier.progress(job_id, round(percent, 1), message)
        exports_repo.set_progress(context.conn, run.export_id, round(percent, 1))

    try:
        if run.cancel_event.is_set():
            exports_repo.mark_cancelled(context.conn, run.export_id)
            context.job_store.mark_cancelled(job_id)
            context.notifier.log("info", "导出已取消")
            return
        voiced = ExportRun(
            export_id=run.export_id,
            project_id=run.project_id,
            plan_row=run.plan_row,
            plan_data=_ensure_voiced(context, run.plan_row, run.plan_data),
            cancel_event=run.cancel_event,
        )
        out_path = render_export(context, voiced, report=report)
        _ensure_titles(context, run.plan_row)
        context.job_store.mark_completed(job_id)
        context.notifier.log("info", f"导出完成: {out_path.name}")
    except Exception as exc:
        if run.cancel_event.is_set() or bool(getattr(exc, "cancelled", False)):
            exports_repo.mark_cancelled(context.conn, run.export_id)
            context.job_store.mark_cancelled(job_id)
            context.notifier.log("info", "导出已取消")
        else:
            exports_repo.mark_failed(context.conn, run.export_id, str(exc))
            context.job_store.mark_failed(job_id, str(exc))
            context.notifier.log("error", f"导出失败: {exc}")
    finally:
        # 与 analysis/narration/models 一致：注册的取消事件必须回收，否则字典无界增长
        context.cancel_events.pop(job_id, None)
