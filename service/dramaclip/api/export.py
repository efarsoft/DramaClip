"""export 命名空间：submit（按方案排队渲染）/ retry（幂等重跑）/ list / list_works。"""

from __future__ import annotations

import json
import shutil
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.api.export_audit import (
    _audit_duration,
    _clock_audit,
    _declared_duration_s,
    _emit_note,
    _log_clock_audit,
    _note_degraded,
    _planned_narration_segments,
    _probe_silence_quality,
    _verify_tts_by_asr,
)
from dramaclip.api.export_covers import (
    SubtitleCover,
    _cover_title,
    _dialogue_ass_lines,
    _extract_cover,
    _plan_cover_promise,
    _subtitle_cover,
    crop_dialogue_lines,
    ensure_covers,
)
from dramaclip.engines.analysis.models import SpeechZone
from dramaclip.engines.bgm import library as bgm_library
from dramaclip.engines.bgm import selector as bgm_selector
from dramaclip.engines.exporter import ai_label, encoder, loudness, selfcheck
from dramaclip.engines.narration import pipeline as narration_pipeline
from dramaclip.engines.narration.conversion import defects
from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.subtitle import presets as subtitle_presets
from dramaclip.engines.subtitle.ass_generator import (
    Canvas,
    build_ass,
    line_char_cap,
    split_subtitle_text,
)
from dramaclip.engines.subtitle.srt import SrtCue, format_srt
from dramaclip.infra import compute, config
from dramaclip.infra.ffmpeg import (
    cover as ffmpeg_cover,  # noqa: F401 - 测试经 export_api.ffmpeg_cover 取模块对象打桩，引用面保留
)
from dramaclip.infra.ffmpeg import probe
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import bgm as bgm_repo
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
_ERR_TRASH_FENCE = -32408  # 产物不在数据目录内，拒绝搬移（models.delete 围栏的同款规矩）
_ERR_TRASH_MOVE = -32409  # 移入回收失败（OSError）：宁留记录，不产无法追溯的孤儿文件
_ERR_PUBLISH_DATA = -32410  # 发布数据录入不合法（W8）：宁拒收，不存脏数据污染回流账

_PUBLISH_PLATFORMS = ("抖音", "快手", "视频号", "小红书", "B站", "其他")


def _now_ms() -> int:
    """录入时刻（毫秒）：与 repo 层时间戳同源同单位。"""
    return int(time.time() * 1000)


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
    router.register("export.delete", lambda params: delete_export(context, params))
    router.register("export.selfcheck", lambda params: selfcheck_batch(context, params))
    router.register("export.set_publish_data", lambda params: set_publish_data(context, params))


@dataclass(frozen=True)
class ExportRun:
    """一次导出渲染的不变输入（export_id 之外全部只读，渲染期间不会改写）。
    """

    export_id: str
    project_id: str
    plan_row: dict[str, Any]
    plan_data: PlanData
    cancel_event: threading.Event
    #: 渲染前阶段（自动音色提取/清洗）的算力回执：与 `video.encode` 并入同一条
    #: `export_jobs.compute` 数组，不另建任务行（规格 §3.5）。
    voice_reports: list[dict[str, Any]] = field(default_factory=list)


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
        voice_issue = _voice_issue_or_none(context, plan_data, project_id)
        if voice_issue is not None:
            rejected.append({"plan_id": plan_id, "reason": voice_issue})
            continue
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


_VOICE_NEEDED_ENGINES = frozenset({"indextts2", "cosyvoice", "cosyvoice3"})


def _auto_voice_available(conn: Any, episode_paths: dict[str, str]) -> bool:
    """可行性判定：本剧剧集里是否存在可自动提取的参考段（带说话人的 4~10s 台词）。"""
    from dramaclip.engines.tts import auto_voice

    rows = [{"id": eid, "source_path": src} for eid, src in episode_paths.items()]
    return auto_voice.pick_best_span(conn, rows) is not None


def _voice_issue_or_none(
    context: AppContext, plan_data: PlanData, project_id: str
) -> str | None:
    """出片受理的配音可行性判定：能自动提取就放行，真不行才拒并说清原因。

    克隆引擎 + 未配参考音色时，**自动从剧集提取**（渲染启动时执行，见
    _ensure_clone_voice）——自动化纪律：用户不看素材，音色从哪来不该问用户。
    只有自动提取也不可行（无带说话人的分析）才拒。
    """
    if not plan_data.narration_texts:
        return None  # 纯原片不需要配音
    from dramaclip.api import narration as narration_api
    from dramaclip.engines.tts import auto_voice

    settings = narration_api._effective_settings(context, project_id)
    engine = str(settings.get("tts.engine") or "edge").strip()
    if engine not in _VOICE_NEEDED_ENGINES:
        return None  # edge/kokoro/auto 链首不需要参考音色
    if str(settings.get(f"tts.voice.{engine}") or "").strip():
        return None  # 已有参考音色
    episode_rows = [
        {"id": row["id"], "source_path": row["source_path"]}
        for row in episodes_repo.list_by_project(context.conn, project_id)
    ]
    if auto_voice.pick_best_span(context.conn, episode_rows) is not None:
        return None  # 可自动提取：渲染启动时补齐
    return (
        "无法自动提取参考音色：本剧已完成分析的剧集中没有主角 4 秒以上的连续台词段。"
        "请先完成剧集分析（含说话人），或把配音引擎切到 Edge（云端免费）/ Kokoro（本地）"
    )


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
    voice_issue = _voice_issue_or_none(context, plan_data, str(record["project_id"]))
    if voice_issue is not None:
        raise RpcDomainError(_ERR_PLAN_NOT_RENDERABLE, voice_issue)
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
    rows = exports_repo.list_by_project(context.conn, str(params.get("project_id", "")))
    return [_decode_json_columns(row, ("selfcheck",)) for row in rows]


def get_export(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """单条导出记录（成片详情页数据源）。"""
    export_id = str(params.get("export_id", ""))
    row = exports_repo.get(context.conn, export_id)
    if row is None:
        raise RpcDomainError(_ERR_EXPORT_NOT_FOUND, f"导出记录不存在: {export_id}")
    return _decode_json_columns(row, ("selfcheck",))


def set_publish_data(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """发布数据录入（W8·MVP）：观众投票是唯一的外部真相源，代理指标全是猜测。

    低摩擦口径：platform/plays/retention_pct 三项必填（十秒填完），likes/
    published_at 可选；键白名单收口，多余键丢弃不存。retention_pct 用 0-100
    的百分数（创作者后台的展示口径，免换算）。data=None 清除录入。
    """
    export_id = str(params.get("export_id", ""))
    if exports_repo.get(context.conn, export_id) is None:
        raise RpcDomainError(_ERR_EXPORT_NOT_FOUND, f"导出记录不存在: {export_id}")
    raw = params.get("data")
    if raw is None:
        exports_repo.set_publish_data(context.conn, export_id, None)
        return {"ok": True, "publish_data": None}
    if not isinstance(raw, dict):
        raise RpcDomainError(_ERR_PUBLISH_DATA, "data 必须是对象或 null")
    platform = str(raw.get("platform", "")).strip()
    if platform not in _PUBLISH_PLATFORMS:
        raise RpcDomainError(
            _ERR_PUBLISH_DATA, f"platform 必须是 {'/'.join(_PUBLISH_PLATFORMS)} 之一"
        )
    try:
        plays = int(str(raw.get("plays")))
        retention = float(str(raw.get("retention_pct")))
    except (TypeError, ValueError) as exc:
        raise RpcDomainError(_ERR_PUBLISH_DATA, f"plays/retention_pct 必填且为数字: {exc}") from exc
    if plays < 0 or not 0 <= retention <= 100:
        raise RpcDomainError(_ERR_PUBLISH_DATA, "plays ≥ 0 且 retention_pct ∈ [0, 100]")
    likes_raw = raw.get("likes")
    likes = None if likes_raw in (None, "") else int(str(likes_raw))
    if likes is not None and likes < 0:
        raise RpcDomainError(_ERR_PUBLISH_DATA, "likes ≥ 0")
    published_at = str(raw.get("published_at") or "").strip() or None
    data = {
        "platform": platform,
        "plays": plays,
        "retention_pct": round(retention, 2),
        "likes": likes,
        "published_at": published_at,
        "recorded_at": _now_ms(),
    }
    exports_repo.set_publish_data(context.conn, export_id, data)
    return {"ok": True, "publish_data": data}


def _decode_json_columns(row: dict[str, Any], columns: tuple[str, ...]) -> dict[str, Any]:
    """TEXT→JSON 列还原成协议形状（selfcheck/episode_ids）；坏 JSON 按缺失处理成
    None（灰），不让一条脏数据把整页列表打成 500。"""
    out = dict(row)
    for column in columns:
        raw = out.get(column)
        if isinstance(raw, str):
            try:
                out[column] = json.loads(raw)
            except json.JSONDecodeError:
                out[column] = None
    return out


def list_works(context: AppContext, params: dict[str, Any]) -> list[dict[str, Any]]:
    """作品库：跨项目已完成成片（附项目名/角度/取材集/自检），limit 可调。

    state 过滤 = 09-10 #30「筛选·自检通过」：passed/failed/partial/unchecked，
    词表外的值当作不筛（缺席容忍，不报错）。
    """
    limit = int(params.get("limit", 60))
    raw_state = params.get("state")
    state = str(raw_state) if raw_state in exports_repo.WORKS_STATE_FILTERS else None
    rows = exports_repo.list_completed_works(context.conn, limit=limit, state=state)
    return [_decode_json_columns(row, ("selfcheck", "episode_ids")) for row in rows]


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
    """画布上限（不是成片尺寸——`resolve_canvas` 会按首集源画幅等比定，ADR-010）：
    读设置键 export.width/height（默认值源在 infra.config），偶数化并钳制最小 480。
    """
    width = max(config.get_int(settings, "export.width"), 480)
    height = max(config.get_int(settings, "export.height"), 480)
    return width - width % 2, height - height % 2


def _load_plan_data(context: AppContext, plan_id: Any) -> PlanData | None:
    """按 id 回读方案并校验；方案被删/数据损坏都返回 None（追溯断链不猜）。"""
    if not plan_id:
        return None
    row = plans_repo.get(context.conn, str(plan_id))
    if row is None:
        return None
    try:
        return PlanData.model_validate(row["plan_data"])
    except Exception as exc:  # noqa: BLE001 - 坏数据不该把整页列表打成 500，但断链必须记账
        _note_degraded(context, "编排方案回读", "自检基准（预算/段数/字幕带）按未知处理", exc)
        return None


def _episode_paths_of(
    context: AppContext, plan_data: PlanData | None
) -> dict[str, str]:
    """方案涉及集的源文件路径表（avsync 互相关的源侧抽取数据面）。"""
    if plan_data is None:
        return {}
    paths: dict[str, str] = {}
    for episode_id in sorted({str(seg.episode_id) for seg in plan_data.timeline}):
        row = episodes_repo.get(context.conn, episode_id)
        if row is not None and row.get("source_path"):
            paths[episode_id] = str(row["source_path"])
    return paths



def _narration_lines_from_cues(
    plan_data: PlanData, segment_index: int, cap: int
) -> list[dict[str, Any]] | None:
    """词界 cue → 解说字幕行（T1 字幕批）：真实词时替代字符比例分配。

    段落配音旁有 .cues.json（edge stream 词界，与 synthesis 缓存同约定）时，
    按词累计到行字数上限封行、行时间=首词起点→末词终点；无 cue/坏数据返回
    None（回退字符比例分配，逐字节兼容旧行为）。
    """
    if not (0 <= segment_index < len(plan_data.timeline)):
        return None
    segment = plan_data.timeline[segment_index]
    slot = segment.narration_id
    if not slot:
        return None
    item = next((t for t in plan_data.narration_texts if t.id == slot), None)
    if item is None or not item.audio_path:
        return None
    audio = Path(str(item.audio_path))
    cue_path = audio.with_name(audio.stem + ".cues.json")
    if not cue_path.is_file():
        return None
    try:
        cues = json.loads(cue_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(cues, list):
        return None
    lines: list[dict[str, Any]] = []
    buf_text = ""
    buf_start: float | None = None
    buf_end: float | None = None
    for cue in cues:
        if not isinstance(cue, dict):
            continue
        word = str(cue.get("text") or "")
        if not word:
            continue
        start = float(cue.get("start") or 0.0)
        end = float(cue.get("end") or 0.0)
        if (
            buf_text
            and buf_start is not None
            and buf_end is not None
            and len(buf_text) + len(word) > cap
        ):
            lines.append(
                {
                    "start": round(buf_start, 3),
                    "end": round(buf_end, 3),
                    "text": buf_text,
                    "emotion_label": segment.emotion_label,
                }
            )
            buf_text = ""
        if not buf_text:
            buf_text, buf_start = word, start
        else:
            buf_text += word
        buf_end = end
    if buf_text and buf_start is not None and buf_end is not None:
        lines.append(
            {
                "start": round(buf_start, 3),
                "end": round(buf_end, 3),
                "text": buf_text,
                "emotion_label": segment.emotion_label,
            }
        )
    return lines or None



def _film_ending_of(
    context: AppContext, plan_data: PlanData | None
) -> tuple[float | None, list[tuple[float, float, str]] | None]:
    """成片最后一刀的源切点与该集台词句表（结尾出点检查的数据面）。

    取**最后一个原声段**：旁白/CTA 收尾不切源素材，词级出点对它无意义。
    集无分析记录/无台词 → (None, None)，检查归灰。
    """
    if plan_data is None:
        return None, None
    originals = [seg for seg in plan_data.timeline if seg.audio == "original"]
    if not originals:
        return None, None
    last = originals[-1]
    record = analysis_repo.get(context.conn, str(last.episode_id))
    if record is None:
        return None, None
    lines = [
        (float(a.start), float(a.end), str(a.text))
        for a in narration_pipeline.parse_asr_segments(
            str(record.get("asr_segments") or "")
        )
    ]
    return float(last.end), lines or None



def _selfcheck_one(context: AppContext, export_id: str) -> bool:
    """单条成片自检并落库；行不在/未完成/产物不在盘上返回 False（保持 NULL，诚实）。

    probe 抛错（文件损坏/无视频轨）也走 False：量不到就不发成绩单，徽章灰「—」。
    """
    row = exports_repo.get(context.conn, export_id)
    if row is None or row["status"] != exports_repo.STATUS_COMPLETED or not row["output_path"]:
        return False
    out_path = Path(str(row["output_path"]))
    if not out_path.is_file():
        return False
    media = probe.probe(out_path)
    plan_data = _load_plan_data(context, row.get("narration_plan_id"))
    ending_end_s, ending_lines = _film_ending_of(context, plan_data)
    avsync_samples = (
        selfcheck.avsync_sample_points(plan_data.timeline) if plan_data is not None else None
    )
    payload = selfcheck.run(
        out_path,
        measured_s=media.duration_s,
        has_audio=media.has_audio,
        mode=str(row["narration_mode"] or ""),
        budget_s=None if plan_data is None else _declared_duration_s(plan_data),
        planned_segments=None if plan_data is None else _planned_narration_segments(plan_data),
        segment_count=0 if plan_data is None else len(plan_data.timeline),
        caption_band=_plan_cover_promise(context, plan_data),
        work_dir=context.work_dir,
        ending_end_s=ending_end_s,
        ending_lines=ending_lines,
        avsync_samples=avsync_samples,
        episode_paths=_episode_paths_of(context, plan_data),
    )
    exports_repo.set_selfcheck(
        context.conn,
        export_id,
        json.dumps(payload, ensure_ascii=False),
        selfcheck.overall_state(payload),
    )
    return True


def selfcheck_batch(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """历史成片补测四项自检（幂等，job 化）：默认只处理已完成且从未自检的记录。

    与 ensure_covers 的同步形状不同：四项度量要整片解码（合并一遍也是秒到分钟
    级），同步 RPC 会卡住界面，所以走作业池由抽屉呈现进度。显式给 export_ids
    则重测指定条目（已有成绩单也覆盖重跑）。
    """
    raw_ids = params.get("export_ids")
    limit = max(min(int(params.get("limit", 200)), 500), 1)
    if isinstance(raw_ids, list) and raw_ids:
        wanted = list(dict.fromkeys(str(item) for item in raw_ids))
        targets = [
            export_id
            for export_id in wanted
            if _selfcheck_target(context, export_id)
        ]
    else:
        missing_rows = exports_repo.list_missing_selfcheck(context.conn, limit)
        targets = [str(row["id"]) for row in missing_rows]
    if not targets:
        return {"ok": True, "job_id": None, "queued": 0}
    job_id = context.job_store.create("export_selfcheck")
    context.executor.submit(
        context.notifier.tracked(job_id, _run_selfcheck_batch, context, job_id, targets)
    )
    return {"ok": True, "job_id": job_id, "queued": len(targets)}


def _selfcheck_target(context: AppContext, export_id: str) -> bool:
    """指定重测的资格：行在、已完成、有产物路径（盘上文件由 _selfcheck_one 再验）。"""
    row = exports_repo.get(context.conn, export_id)
    return bool(
        row is not None
        and row["status"] == exports_repo.STATUS_COMPLETED
        and row["output_path"]
    )


def _run_selfcheck_batch(context: AppContext, job_id: str, export_ids: list[str]) -> None:
    """作业体：逐条自检，单条失败不断批（那条保持 NULL 灰），进度按条报。"""
    context.job_store.mark_running(job_id)
    total = len(export_ids)
    checked = 0
    try:
        for index, export_id in enumerate(export_ids, start=1):
            context.job_store.set_progress(
                job_id, round((index - 1) / total * 100, 1), f"成片自检 {index}/{total}"
            )
            try:
                if _selfcheck_one(context, export_id):
                    checked += 1
            except Exception as exc:  # noqa: BLE001 - 单条量不了不断整批，但要点名是哪条
                _note_degraded(
                    context, f"成片自检（第 {index}/{total} 条 {export_id}）",
                    "该行成绩单留 NULL（徽章灰）", exc,
                )
        context.job_store.mark_completed(job_id)
        context.notifier.log("info", f"成片自检完成：{checked}/{total} 条拿到成绩单")
    except Exception as exc:
        context.job_store.mark_failed(job_id, str(exc))
        context.notifier.log("error", f"成片自检批次失败: {exc}")


def delete_export(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """删除一条成片（09-10 §3.4 危险操作规矩）：文件先移入 <data>/.trash/<日期>/ 再删行。

    可恢复性落在文件层：成片、封面与逐句时间轴旁挂文件都搬（不搬就成孤儿），「关于 →
    本地数据」入口可达 .trash；DB 行硬删（与 project.delete 同先例）。两类失败分开对待：
    文件不在盘上 → 如实报 missing、不挡删行（记录指向的东西本来已经没了）；
    围栏/OSError → 整单拒绝（宁留记录，不产无法追溯的孤儿文件）。
    """
    export_id = str(params.get("export_id", ""))
    row = exports_repo.get(context.conn, export_id)
    if row is None:
        raise RpcDomainError(_ERR_EXPORT_NOT_FOUND, f"导出记录不存在: {export_id}")
    root = context.data_dir.resolve()
    trash_dir = root / ".trash" / date.today().isoformat()
    trashed: list[str] = []
    missing: list[str] = []
    targets: list[Path] = []
    for key in ("output_path", "cover_path"):
        raw = row.get(key)
        if raw:
            targets.append(Path(str(raw)))
    sidecar = Path(str(row["output_path"])).with_suffix(".srt") if row.get("output_path") else None
    if sidecar is not None and sidecar.is_file():
        # 逐句时间轴旁挂文件不在 DB 列里（路径由成片名推出），盘上有就得跟着走
        targets.append(sidecar)
    for path in targets:
        if not path.is_file():
            missing.append(str(path))
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise RpcDomainError(_ERR_TRASH_FENCE, f"产物不在数据目录内，拒绝搬移: {path}")
        try:
            trash_dir.mkdir(parents=True, exist_ok=True)
            dest = trash_dir / resolved.name
            if dest.exists():
                dest = trash_dir / f"{export_id[:6]}_{resolved.name}"
            shutil.move(str(resolved), str(dest))
        except OSError as exc:
            raise RpcDomainError(_ERR_TRASH_MOVE, f"移入回收失败: {exc}") from exc
        trashed.append(str(dest))
    exports_repo.delete(context.conn, export_id)
    return {"ok": True, "trashed": trashed, "missing": missing}


def _pick_bgm_track(context: AppContext, plan_data: PlanData) -> Path | None:
    """BGM 床选曲（C 项接线层唯一入口）：设置/曲库两层门禁（模式门禁在 selector 内）。

    返回 None 的所有情形都是合法态＝现状出片：设置关、表读不了、库空、该模式
    不该铺（raw_clip/dialogue_narration 源片自带 BGM）、情绪无曲且 default 也无、
    曲目文件已不在盘上。「无曲可用＝逐字节一致」是 selector 的硬验收，这里不猜。
    """
    if not config.get_bool(context.settings, "export.bgm"):
        return None
    try:
        rows = bgm_repo.list_all(context.conn)
    except Exception as exc:  # noqa: BLE001 - 曲库读不了不挡导出
        _note_degraded(context, "BGM 曲库读取", "本条成片不铺 BGM 床", exc)
        return None
    tracks = [bgm_library.track_from_row(row) for row in rows]
    track = bgm_selector.select_bgm(plan_data, tracks)
    if track is None:
        return None
    if not track.file.is_file():
        _note_degraded(
            context, "BGM 曲目文件缺失", "本条成片不铺 BGM 床（请重扫素材库）", None
        )
        return None
    bpm = f"{track.bpm:.0f}bpm" if track.bpm is not None else "bpm未测"
    _emit_note(
        context, "info", f"BGM 床：{track.file.name}（{track.emotion}，{bpm}，音量 15%）"
    )
    return track.file


def render_export(
    context: AppContext,
    run: ExportRun,
    *,
    report: Callable[[float, str], None],
    job_id: str | None = None,
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
    # 原声段台词字幕的源（批次二）：同一份 asr_segments JSON 的**原始 dict** 视图，
    # 带 text/words（SpeechZone 只有 start/end，是 jitter 保护区的最小形状，不改它）。
    dialogue_items: dict[str, list[dict[str, Any]]] = {}
    subtitle_bands: dict[str, tuple[float, float]] = {}
    # 行级擦除矩形（2026-10-07 业主追加：只擦检测到的文字行，不擦整带）
    subtitle_line_rects: dict[str, list[tuple[float, float]]] = {}
    # 台词驻留窗（2026-10-09 业主追加：擦除只在有字的那几秒挂）：episode_id → 源绝对秒
    subtitle_erase_windows: dict[str, list[tuple[float, float]]] = {}
    for segment in plan_data.timeline:
        episode_id = segment.episode_id
        if episode_id in dialogue_zones:
            continue
        record = analysis_repo.get(context.conn, episode_id)
        if record is None:
            continue
        cover = _subtitle_cover(record)
        if cover.band is not None:
            subtitle_bands[episode_id] = cover.band
        if cover.line_rects:
            subtitle_line_rects[episode_id] = list(cover.line_rects)
        if cover.dwell_windows:
            subtitle_erase_windows[episode_id] = list(cover.dwell_windows)
        if not record["asr_segments"]:
            continue
        try:
            raw_items = json.loads(record["asr_segments"])
        except (TypeError, json.JSONDecodeError):
            continue
        zones = [
            SpeechZone(start=float(item["start"]), end=float(item["end"]))
            for item in raw_items
            if isinstance(item, dict)
            and float(item.get("end", 0)) > float(item.get("start", 0))
        ]
        if zones:
            dialogue_zones[episode_id] = zones
        items = [
            item
            for item in raw_items
            if isinstance(item, dict)
            and isinstance(item.get("start"), (int, float))
            and isinstance(item.get("end"), (int, float))
            and float(item["end"]) > float(item["start"])
        ]
        if items:
            dialogue_items[episode_id] = items

    tts_segments = tts_audio_by_segment(plan_data)
    preset = subtitle_presets.get_preset(context.settings.get("subtitle.default_preset"))
    # 画布跟随首个源集画幅（16:9 进→16:9 出，不裁不拉；settings 尺寸只当上限盒）。
    # ASS 的 PlayRes/字号/拆行上限与编码器 out_size 必须同一画布——两边各算一份
    # 就是「字幕超出屏幕」的新产房。
    out_size = encoder.resolve_canvas(episode_paths, _output_size(context.settings))
    ass_canvas = Canvas(*out_size)

    def cover_rect(episode_id: str) -> tuple[float, float] | None:
        """压位定位的目标矩形（并集口径的唯一实现处见 `SubtitleCover.cover_rect`）。"""
        return SubtitleCover(
            band=subtitle_bands.get(episode_id),
            line_rects=tuple(subtitle_line_rects.get(episode_id) or ()),
        ).cover_rect

    # 台词时钟对账（立案④）：逐段记 (烧录行数, 可对照行数, 零重叠行数)，出片后汇总一条明账。
    clock_stats: list[tuple[int, int, int]] = []
    # 逐段收下的**段内相对**字幕行，出片后按 Phase B 实测偏移搬到成片刻度（H1）
    burned_lines: dict[int, list[tuple[float, float, str]]] = {}

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
        cap = line_char_cap(preset, ass_canvas)
        # 词界 cue 优先（T1 字幕批）：段落配音旁有 .cues.json（edge stream 词界）
        # 时按真实词时切行；无 cue（indextts2/kokoro 等引擎）回退标点断句+字符比例。
        cue_lines = _narration_lines_from_cues(plan_data, segment_index, cap)
        if cue_lines is not None:
            lines = cue_lines
        else:
            chunks = split_subtitle_text(text, cap)
            total_chars = sum(len(c) for c in chunks)
            emotion = None
            if 0 <= segment_index < len(plan_data.timeline):
                emotion = plan_data.timeline[segment_index].emotion_label
            lines = []
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

        burned_lines[segment_index] = [
            (float(line["start"]), float(line["end"]), str(line["text"])) for line in lines
        ]
        ass_path.write_text(
            build_ass(
                lines,
                preset,
                source_band=cover_rect(
                    plan_data.timeline[segment_index].episode_id
                    if 0 <= segment_index < len(plan_data.timeline)
                    else ""
                ),
                play_res=out_size,
            ),
            encoding="utf-8",
        )
        return str(ass_path)

    def dialogue_subtitle(segment_index: int, win_start: float, win_end: float) -> str | None:
        """原声段台词字幕（批次二·方案 B 的回调实现）：ASR 句按实际切割窗口做词级
        裁剪，写成段级 ass（相对时间轴 0→窗口长），窗口内没台词返回 None（不烧）。

        窗口是 encoder 传的 **safe_times 之后的真实切点**：抖动挪过的段，按声明
        start/end 预生成的字幕会整体错位，所以裁剪必须在这里做、拿这个窗口做。
        """
        if not (0 <= segment_index < len(plan_data.timeline)):
            return None
        episode_id = plan_data.timeline[segment_index].episode_id
        items = dialogue_items.get(episode_id) or []
        cropped = crop_dialogue_lines(items, win_start, win_end)
        if not cropped:
            return None
        cap = line_char_cap(preset, ass_canvas)
        lines: list[dict[str, Any]] = []
        for item in cropped:
            lines.extend(_dialogue_ass_lines(item, cap))
        if not lines:
            return None
        burned_lines[segment_index] = [
            (float(line["start"]), float(line["end"]), str(line["text"])) for line in lines
        ]
        ass_dir = context.work_dir / "export" / export_id
        ass_dir.mkdir(parents=True, exist_ok=True)
        ass_path = ass_dir / f"seg_{segment_index:03d}.ass"
        ass_path.write_text(
            build_ass(lines, preset, source_band=cover_rect(episode_id), play_res=out_size),
            encoding="utf-8",
        )
        checked, stray = _clock_audit(
            cropped, win_start, subtitle_erase_windows.get(episode_id) or []
        )
        clock_stats.append((len(cropped), checked, stray))
        return str(ass_path)

    # 输出编码：auto=硬编探测（黑帧实编验证，NVENC/QSV/VT 按平台候选），失败/关闭回退 libx264
    codec_setting = str(context.settings.get("export.encoder", "auto") or "auto").lower()
    if codec_setting == "auto":
        # A4：auto 用硬编探测选中的编码器（NVENC/QSV/VideoToolbox 按平台候选序），
        # 全不可用回 libx264。硬编某段真编失败时段级自动回退 libx264（encoder 内），
        # 签名不齐的 concat 自动整体重编码——「导出到 90% 崩」由回退链兜住。
        video_codec = encoder.pick_hw_encoder() or "libx264"
    else:
        video_codec = codec_setting
    # 算力回执：导出成功才落库（失败没有「这次用了什么」的终态可言）；
    # export_jobs 与 jobs 两处同写，界面读哪张表都不会各说各话。
    reports: list[compute.ComputeReport] = []
    # 拼接清单上的实测偏移（成片逐句时间轴的刻度来源）；成功轮只会到一份，取最后一条
    offsets_emitted: list[Sequence[tuple[int, float]]] = []
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
        original_subtitle_provider=(
            dialogue_subtitle if plan_data.mode != "raw_clip" else None
        ),
        dialogue_zones=dialogue_zones,
        subtitle_bands=subtitle_bands,
        subtitle_erase_rects=subtitle_line_rects,
        subtitle_erase_windows=subtitle_erase_windows,
        out_size=out_size,
        loudness_target=loudness.LoudnessTarget.from_settings(context.settings),
        # AI 生成标注（业主裁决 2026-10-15：用户开关、默认关闭；键名由 ai_label 模块单持）
        burn_ai_label=ai_label.enabled(context.settings),
        compute_sink=reports.append,
        encoder_requested=codec_setting,
        segment_offsets_sink=offsets_emitted.append,
        # BGM 床（C 项接线）：设置/模式/曲库三层门禁在 _pick_bgm 内，任一层不过
        # 返回 None＝现状出片。混音失败在 encoder 层向上抛，这里降级留痕不挡导出。
        bgm_track=_pick_bgm_track(context, plan_data),
    )
    # 清洗在前、编码在后：读账的人按时间顺序看（规格 §3.5）
    receipt = [*run.voice_reports, *(item.to_dict() for item in reports)]
    exports_repo.set_compute(context.conn, export_id, receipt)
    if job_id is not None:
        context.job_store.set_compute(job_id, receipt)
    _log_clock_audit(context, clock_stats)
    exports_repo.mark_completed(context.conn, export_id, str(out_path))
    _write_film_srt(
        context, out_path, burned_lines,
        dict(offsets_emitted[-1]) if offsets_emitted else None,
    )
    try:
        media = probe.probe(out_path)
        exports_repo.set_meta(
            context.conn, export_id, duration_s=media.duration_s, size_bytes=out_path.stat().st_size
        )
        _audit_duration(context, plan_data, media.duration_s)
    except (ValueError, OSError) as exc:
        # 元信息回填/时长审计失败不影响导出成功——但"没回填、没核对"必须写进账面
        _note_degraded(context, "成片元信息回填与时长审计", "库里没有实测时长，事后核对也没做", exc)
    # 成片静默体检（W6）：零文案模式跳过；解说模式无声开场/结尾、中段死气段留痕
    # （_probe_silence_quality 自带 try-except，不会抛出）
    _probe_silence_quality(
        context, str(out_path), str(plan_row["narration_mode"] or ""),
    )
    # 四项自检（09-10 #29：导出期产出字段）：增强项绝不挡导出，留 NULL 也要留痕
    try:
        _selfcheck_one(context, export_id)
    except Exception as exc:  # noqa: BLE001 - 自检失败不许把已拼好的片拖成失败
        _note_degraded(context, "导出期四项自检", "成绩单留 NULL，可在成片列表重测", exc)
    try:
        _extract_cover(
            context,
            export_id,
            out_path,
            title=_cover_title(context, plan_row),
            plan_data=plan_data,
            episode_paths=episode_paths,
            out_size=out_size,
        )  # 封面失败不影响导出成功（源截帧→成片截帧的降级链在 _extract_cover 内）
    except (OSError, ValueError) as exc:
        _note_degraded(context, "封面截帧", "本条成片没有封面（列表用占位图）", exc)
    return out_path


def _write_film_srt(
    context: AppContext,
    out_path: Path,
    burned_lines: dict[int, list[tuple[float, float, str]]],
    offsets: dict[int, float] | None,
) -> None:
    """成片同名 `.srt`：段内相对字幕时刻 + Phase B 实测段偏移＝成片刻度。

    偏移来自渲染层拼接清单的实测段长，不是 `timeline[].start/end` 声明窗口——后者不含
    抖动切点与保护区外扩，用它凑出来的时间轴整条错位，跳到的是别的句子（比没有更坏，
    且看不出来）。所以量不到就**不落盘**，只记一条允许型降级。
    不烧字幕的模式（raw_clip）本来没有逐句可核对：空账不是降级。
    """
    rows = [
        (index, start, end, text)
        for index in sorted(burned_lines)
        for (start, end, text) in burned_lines[index]
    ]
    if not rows:
        return
    if offsets is None or any(row[0] not in offsets for row in rows):
        _note_degraded(context, "成片逐句时间轴", "出片页点不开逐句核对，只有视频本身")
        return
    try:
        out_path.with_suffix(".srt").write_text(
            format_srt(
                [
                    SrtCue(offsets[index] + start, offsets[index] + end, text)
                    for index, start, end, text in rows
                ]
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        _note_degraded(context, "成片逐句时间轴", "出片页点不开逐句核对（旁挂文件没写成）", exc)


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

    voiced = narration_api._voice(context, plan_data, settings, durations, on_progress=tts_progress)
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
        # 进度波段：需配音时 TTS 占 0~35%、渲染占 35~100；纯剪辑渲染独占 0~100
        tts_needed = _needs_voice(run.plan_data)
        voice_reports: list[dict[str, Any]] = []
        voiced = ExportRun(
            export_id=run.export_id,
            project_id=run.project_id,
            plan_row=run.plan_row,
            plan_data=_ensure_voiced(
                context, run.plan_row, run.plan_data,
                report=report if tts_needed else None,
                voice_reports=voice_reports,
            ),
            cancel_event=run.cancel_event,
            voice_reports=voice_reports,
        )
        # 标题先生成再渲染：render_export 尾部的封面字层要用第一条标题，
        # 而 titles 生成不依赖渲染产物（LLM 只吃 plan_data），顺序对调零副作用。
        _ensure_titles(context, run.plan_row)
        # TTS 回环校验（开关 export.tts_verify 默认关）：合成旁白过本地 ASR 比对
        # 文案，错读/漏字留痕点名——渲染前做，账面跟片走；失败不挡导出（函数内兜）。
        _verify_tts_by_asr(context, run.plan_data)
        render_report = (
            (lambda pct, label: report(35 + pct * 0.65, label)) if tts_needed else report
        )
        out_path = render_export(context, voiced, report=render_report, job_id=job_id)
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
