"""导出前配音准备：确保方案在渲染前有可用配音与标题。

自 export_render.py 拆出（拆分专项）：`_ensure_voiced` 在渲染前合成旁白
（含自动音色提取）、`_ensure_clone_voice` 为克隆引擎从剧集自动提取参考
音色、`_ensure_titles` 生成候选标题——三者都是「渲染前的增强项，失败
留痕不挡导出」。调用方是 api/export.py 的 `_run_export`。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.api.export_audit import _note_degraded
from dramaclip.engines.narration.models import PlanData
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import plans as plans_repo

_VOICE_NEEDED_ENGINES = frozenset({"indextts2", "cosyvoice", "cosyvoice3"})


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


def _ensure_voiced(
    context: AppContext,
    plan_row: dict[str, Any],
    plan_data: PlanData,
    report: Callable[[float, str], None] | None = None,
    voice_reports: list[dict[str, Any]] | None = None,
    cancel: threading.Event | None = None,
) -> PlanData:
    """勾选导出时才配音：规划阶段故意不合成。克隆引擎没有参考音色时，
    先**自动从剧集提取**（主角最清晰的 4~10s 台词段，人声分离去 BGM）——
    自动化纪律：音色从哪来不该问用户，剧集本身就是最好的音色库。

    `report`：TTS 段进度出口（占导出进度 0~35% 波段）——TTS 是导出耗时大头，
    恒 0% 会被当成卡死（业主实测反馈）。
    `voice_reports`：渲染前那次音色提取的算力回执落点（导出账的首位）。"""
    if not _needs_voice(plan_data):
        return plan_data
    from dramaclip.api import narration as narration_api

    project_id = str(plan_row["project_id"])
    durations = {
        str(episode["id"]): float(episode["duration"] or 0.0)
        for episode in episodes_repo.list_by_project(context.conn, project_id)
    }
    settings = narration_api._effective_settings(context, project_id)
    _ensure_clone_voice(
        context, plan_row, project_id, episodes_repo, settings, voice_reports
    )

    def tts_progress(done: int, total: int) -> None:
        if report is not None:
            report(round(35 * done / total, 1), f"配音合成 {done}/{total} 段")

    voiced = narration_api._voice(
        context, plan_data, settings, durations,
        on_progress=tts_progress, cancel=cancel,
    )
    plans_repo.update_plan_data(context.conn, str(plan_row["id"]), voiced.model_dump())
    if _needs_voice(voiced):
        raise ValueError("旁白音频合成失败，不能用原声顶替")
    return voiced


def _ensure_clone_voice(
    context: AppContext,
    plan_row: dict[str, Any],
    project_id: str,
    episodes_repo: Any,
    settings: dict[str, str],
    voice_reports: list[dict[str, Any]] | None = None,
) -> None:
    """克隆引擎 + 未配参考音色 → 自动从本剧剧集提取主角音色并设为参考。

    用带说话人标签的分析数据：选台词字数最多的主角最清晰的 4~10s 连续段。
    写 DB + 就地改 settings 快照（后续 voice_for 读同一 dict）。提取失败
    （无分析/源缺失）原样抛——导出按失败处理，理由如实。

    一批出片会多条任务并发走到这里：提取全程持锁，且锁内重读 DB——
    手动提取按钮或兄弟任务刚写好的音色直接复用，不重复跑 MDX 分离。
    这次用哪块算力洗的参考，回执 append 进 `voice_reports`（导出账的首位）。
    """
    from dramaclip.engines.tts import auto_voice
    from dramaclip.infra.storage.repos import settings as settings_repo

    engine = str(settings.get("tts.engine") or "edge").strip()
    if engine not in _VOICE_NEEDED_ENGINES:
        return
    voice_key = f"tts.voice.{engine}"
    if str(settings.get(voice_key) or "").strip():
        return  # 已有参考音色
    with auto_voice.extract_lock():
        fresh = str(settings_repo.get_all(context.conn).get(voice_key) or "").strip()
        if fresh:
            settings[voice_key] = fresh
            return
        episode_rows = [
            {"id": row["id"], "source_path": row["source_path"]}
            for row in episodes_repo.list_by_project(context.conn, project_id)
            if row["status"] == "done"
        ]
        picked = auto_voice.pick_best_span(context.conn, episode_rows)
        if picked is None:
            raise ValueError(
                "无法自动提取参考音色：本剧剧集分析里没有主角 4 秒以上的连续台词段。"
                "请先完成剧集分析，或在引擎中心把配音引擎切到 Edge（云端免费）"
            )
        row, start, end, speaker = picked
        result = auto_voice.extract_auto_voice(
            context.conn,
            context.data_dir,
            [{"id": row["id"], "source_path": row["source_path"]}],
        )
        if voice_reports is not None and result.get("compute") is not None:
            voice_reports.append(dict(result["compute"]))
        settings[voice_key] = result["path"]
        settings_repo.set_value(context.conn, voice_key, result["path"])
        clean_note = (
            f"滤镜清洗（人声分离不可用：{result.get('clean_reason') or '未知原因'}）"
            if result.get("cleaned_with") == "filter"
            else "人声分离完成"
        )
        context.notifier.log(
            "info",
            f"已自动从剧集提取参考音色（{speaker}，{result['seconds']}s，{clean_note}）"
            f"并设为 {engine} 参考",
        )


def _ensure_titles(context: AppContext, plan_row: dict[str, Any]) -> None:
    """成片落库时带 8 条标题；已有标题或 LLM 不可用都不挡导出——但断供必须留痕。"""
    if plan_row.get("titles"):
        return
    from dramaclip.api import narration as narration_api

    try:
        narration_api.generate_titles(context, {"plan_id": str(plan_row["id"])})
    except Exception as exc:  # noqa: BLE001 - 标题是增强项，不许把已渲染的片子拖成失败
        _note_degraded(context, "候选标题生成", "封面没有字层标题、列表也无候选可选", exc)
