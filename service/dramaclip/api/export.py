"""export 命名空间：submit（按方案排队渲染）/ retry（幂等重跑）/ list / list_works。"""

from __future__ import annotations

import contextlib
import json
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.engines.analysis.models import SpeechZone
from dramaclip.engines.exporter import encoder, loudness, selfcheck
from dramaclip.engines.narration.conversion import defects
from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.subtitle import presets as subtitle_presets
from dramaclip.engines.subtitle.ass_generator import (
    TRAILING_MARKS,
    Canvas,
    build_ass,
    line_char_cap,
    split_subtitle_text,
)
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
_ERR_TRASH_FENCE = -32408  # 产物不在数据目录内，拒绝搬移（models.delete 围栏的同款规矩）
_ERR_TRASH_MOVE = -32409  # 移入回收失败（OSError）：宁留记录，不产无法追溯的孤儿文件

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
    rows = exports_repo.list_by_project(context.conn, str(params.get("project_id", "")))
    return [_decode_json_columns(row, ("selfcheck",)) for row in rows]


def _cover_title(context: AppContext, plan_row: dict[str, Any]) -> str | None:
    """封面字层用标题：取方案的第一条候选标题。

    plan_row 自带 titles 优先；为空时回库重读——`_ensure_titles` 可能刚生成完，
    而 render_export 手里的 plan_row 是提交时的旧快照。封面属增强项：任何异常
    都退回无字层，绝不挡导出。
    """
    try:
        titles = plan_row.get("titles") or []
        if not titles:
            row = plans_repo.get(context.conn, str(plan_row["id"]))
            titles = (row or {}).get("titles") or []
        first = str(titles[0]).strip() if titles else ""
        return first or None
    except Exception:  # noqa: BLE001 - 增强项失败退回无字层截帧
        return None


def _cover_source_frame(
    plan_data: PlanData, episode_paths: dict[str, str], out_size: tuple[int, int]
) -> tuple[Path, float, str] | None:
    """A1：封面源截帧的输入——(源文件, 源时间戳, 构图滤镜链)；拿不到就 None（退回成片截）。

    映射公式：源时间戳 = 时间轴**首段** start + 1.5（与成片钩帧「1.5s 处」同一画面
    内容，但取自源素材、无烧录字幕）。构图链与 encoder 同语义：等比缩放进画布
    （decrease）+ 不足处补黑——封面构图=成片构图。eq/fade/setpts/ass 不接
    （理由见 infra/ffmpeg/cover.py）。

    None 的判据（每条都走 _extract_cover 的成片回退）：时间轴为空 / episode_paths
    无首段那集 / 源文件不存在。
    """
    if not plan_data.timeline:
        return None
    first = plan_data.timeline[0]
    raw = episode_paths.get(first.episode_id)
    if raw is None:
        return None
    source = Path(raw)
    if not source.is_file():
        return None
    seek_s = first.start + 1.5
    composition = (
        f"scale={out_size[0]}:{out_size[1]}:force_original_aspect_ratio=decrease,"
        f"pad={out_size[0]}:{out_size[1]}:(ow-iw)/2:(oh-ih)/2:color=black"
    )
    return source, seek_s, composition


def _extract_cover(
    context: AppContext,
    export_id: str,
    out_path: Path,
    *,
    title: str | None = None,
    plan_data: PlanData | None = None,
    episode_paths: dict[str, str] | None = None,
    out_size: tuple[int, int] | None = None,
) -> None:
    """成品封面：优先从**源素材**截帧（无烧录字幕），失败退回成片截帧。

    降级顺序（全程不 raise，封面属增强项）：
    1. 源截帧（plan_data/episode_paths/out_size 齐备且源文件在盘上）；
    2. 源截帧失败或未提供源输入 → 成片截帧（现状行为，带字幕仍比没封面强）；
    3. 都失败 → 不落库（UI 占位图兜底）。
    封面已存在直接 return（幂等）。
    """
    covers_dir = context.data_dir / "covers" / "exports"
    covers_dir.mkdir(parents=True, exist_ok=True)
    cover_path = covers_dir / f"{export_id}.jpg"
    if cover_path.is_file():
        return
    source_frame: tuple[Path, float, str] | None = None
    if plan_data is not None and episode_paths is not None and out_size is not None:
        try:
            source_frame = _cover_source_frame(plan_data, episode_paths, out_size)
        except Exception:  # noqa: BLE001 - 增强项自诊断失败也退回成片截
            source_frame = None
    if source_frame is not None:
        source, seek_s, composition = source_frame
        if ffmpeg_cover.extract_cover(
            source, cover_path, seek_s=seek_s, title=title, composition_vf=composition
        ):
            exports_repo.set_cover(context.conn, export_id, str(cover_path))
            return
    if ffmpeg_cover.extract_cover(out_path, cover_path, title=title):
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
        title: str | None = None
        plan_id = str(row.get("narration_plan_id") or "")
        if plan_id:
            plan_row = plans_repo.get(context.conn, plan_id)
            if plan_row is not None:
                title = _cover_title(context, plan_row)
        if ffmpeg_cover.extract_cover(out_path, cover_path, title=title):
            exports_repo.set_cover(context.conn, str(row["id"]), str(cover_path))
            generated += 1
    return {"ok": True, "generated": generated}


def get_export(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """单条导出记录（成片详情页数据源）。"""
    export_id = str(params.get("export_id", ""))
    row = exports_repo.get(context.conn, export_id)
    if row is None:
        raise RpcDomainError(_ERR_EXPORT_NOT_FOUND, f"导出记录不存在: {export_id}")
    return _decode_json_columns(row, ("selfcheck",))


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
    """输出分辨率：读设置键 export.width/height（默认值源在 infra.config），偶数化并钳制最小 480。
    """
    width = max(config.get_int(settings, "export.width"), 480)
    height = max(config.get_int(settings, "export.height"), 480)
    return width - width % 2, height - height % 2


# 渲染后时长审计的容差不在这里：判据统一由 encoder.AUDIT_DURATION_* 发号
# （dedup 微变速 ±0.4%、切点抖动、AAC/concat 毫秒级出入都在它的预算里），
# 本层只引用——第二处字面量等于第二套判据，改一处就会出现「界面绿、日志 warn」。


def _as_float(value: Any) -> float | None:
    """JSON 里的时间戳 → float；不是数就 None（坏行逐个跳过，不炸整段渲染）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def crop_dialogue_lines(
    items: list[dict[str, Any]], win_start: float, win_end: float
) -> list[dict[str, Any]]:
    """把库内 ASR 句按段切割窗口 [win_start, win_end] 裁成段内台词行（批次二）。

    返回元素形状 {start, end, text, words}：start/end 是**重定基到窗口起点的相对秒**，
    words 是同基的词表（[{start,end,word}]）或 None（句级降级）。

    词级裁剪（FunClip 的多数重叠思路）：跨界词按「与窗口的重叠 ≥ 词长一半」归属——
    一半以上音节落在段内，观众就能在本段听到它，字幕跟声音走；恰好压线归本段
    （前半在本段听得到，后半切掉了也要把词标出来，否则台词缺字）。

    无 words 的旧库（words 空/缺失）降级为句级：整句与窗口有交集就显示整句，
    区间钳到窗口——旧数据不 raise，也不假装能词级对齐。
    """
    cropped: list[dict[str, Any]] = []
    if win_end <= win_start:
        return cropped
    for item in items:
        if not isinstance(item, dict):
            continue
        s = _as_float(item.get("start"))
        e = _as_float(item.get("end"))
        if s is None or e is None or e <= s or e <= win_start or s >= win_end:
            continue  # 坏行或与窗口无交集
        text = str(item.get("text") or "").strip()
        raw_words = item.get("words")
        valid_words: list[dict[str, Any]] = []
        if isinstance(raw_words, list):
            for word in raw_words:
                if not isinstance(word, dict):
                    continue
                ws = _as_float(word.get("start"))
                we = _as_float(word.get("end"))
                wt = str(word.get("word") or "")
                if ws is None or we is None or we <= ws or not wt:
                    continue
                valid_words.append({"ws": ws, "we": we, "wt": wt})
        if text and valid_words:
            kept: list[dict[str, Any]] = []
            for entry in valid_words:
                ws, we, wt = entry["ws"], entry["we"], entry["wt"]
                length = we - ws
                overlap = min(we, win_end) - max(ws, win_start)
                if overlap * 2 < length:
                    continue  # 跨界词：重叠不足一半，归另一段
                kept.append(
                    {
                        "start": max(ws, win_start) - win_start,
                        "end": min(we, win_end) - win_start,
                        "word": wt,
                    }
                )
            if kept:
                cropped.append(
                    {
                        "start": kept[0]["start"],
                        "end": kept[-1]["end"],
                        "text": "".join(w["word"] for w in kept),
                        "words": kept,
                    }
                )
            # 有词级数据但一个词都没留在窗口内：这句在本段听不到，也不显示——
            # 回退整句会把观众听不到的词烧上屏（降级只留给**没有**词级数据的旧库）。
            continue
        if not text:
            continue
        # 句级降级：整句钳到窗口
        cropped.append(
            {
                "start": max(s, win_start) - win_start,
                "end": min(e, win_end) - win_start,
                "text": text,
                "words": None,
            }
        )
    return cropped


def _dialogue_word_chunks(
    words: list[dict[str, Any]], cap: int
) -> list[tuple[float, float, str]]:
    """词表 → (start, end, text) 行块：贪心攒词到上限；单词超限在词内硬切，
    时间按字数在词时长上线性内插（时间仍出自 words 时间戳，只是细到字）。"""
    chunks: list[tuple[float, float, str]] = []
    cur_start: float | None = None
    cur_end = 0.0
    cur_text = ""
    for word in words:
        wt = str(word.get("word") or "")
        ws = float(word["start"])
        we = float(word["end"])
        total = len(wt)
        consumed = 0
        while consumed < total:
            room = cap - len(cur_text)
            if room <= 0:
                assert cur_start is not None
                chunks.append((cur_start, cur_end, cur_text))
                cur_start, cur_end, cur_text = None, 0.0, ""
                continue
            take = min(room, total - consumed)
            p0 = ws + (we - ws) * consumed / total
            p1 = ws + (we - ws) * (consumed + take) / total
            if cur_start is None:
                cur_start = p0
            cur_end = p1
            cur_text += wt[consumed : consumed + take]
            consumed += take
    if cur_start is not None and cur_text:
        chunks.append((cur_start, cur_end, cur_text))
    return chunks


def _dialogue_ass_lines(item: dict[str, Any], cap: int) -> list[dict[str, Any]]:
    """一条裁剪后的台词 → ass 行元素（相对段起点的时间轴，同 narration 字幕形状）。

    有 words：时长按词时间戳（一行一句/词组）；无 words（句级降级）：拆行后
    时长按字数比例分配整句区间——与 burn_subtitle 的既有规矩一致。"""
    text = str(item["text"])
    start = float(item["start"])
    end = float(item["end"])
    words = item.get("words")
    lines: list[dict[str, Any]] = []
    if isinstance(words, list) and words:
        for ws, we, wt in _dialogue_word_chunks(words, cap):
            cleaned = wt.rstrip(TRAILING_MARKS)
            if cleaned and we > ws:
                lines.append({"start": ws, "end": we, "text": cleaned})
        return lines
    chunks = split_subtitle_text(text, cap)
    total_chars = sum(len(chunk) for chunk in chunks)
    if total_chars <= 0 or end <= start:
        return lines
    cursor = start
    for chunk in chunks:
        span = (end - start) * len(chunk) / total_chars
        lines.append({"start": cursor, "end": cursor + span, "text": chunk})
        cursor += span
    return lines


def _audit_duration(context: AppContext, plan_data: PlanData, actual_s: float) -> None:
    """实测时长 vs 时间轴声明总时长（sum(end-start)）：超阈值只写 warn 明账。

    审计自身任何异常都静默吞掉——它是事后体检，绝不反过来挡已成功的导出。
    """
    with contextlib.suppress(Exception):
        declared = sum(max(seg.end - seg.start, 0.0) for seg in plan_data.timeline)
        if declared <= 0:
            return
        diff = actual_s - declared
        tolerance = max(
            declared * encoder.AUDIT_DURATION_REL_TOLERANCE,
            encoder.AUDIT_DURATION_ABS_TOLERANCE_S,
        )
        if abs(diff) <= tolerance:
            return
        context.notifier.log(
            "warn",
            f"成片时长审计：实测 {actual_s:.1f}s vs 声明 {declared:.1f}s"
            f"（差 {diff:+.1f}s，超出阈值 ±{tolerance:.1f}s）——成片可能缺段/重复，请人工核对",
        )


def _declared_duration_s(plan_data: PlanData) -> float | None:
    """时间轴声明总时长（Σ end-start）；<=0 视为拿不到预算（None，自检该项归灰）。"""
    declared = sum(max(seg.end - seg.start, 0.0) for seg in plan_data.timeline)
    return declared if declared > 0 else None


def _planned_narration_segments(plan_data: PlanData) -> int:
    """方案里的旁白段数（narration/ducked）：自检「含配音」的判据源。"""
    return sum(1 for seg in plan_data.timeline if seg.audio in ("narration", "ducked"))


def _load_plan_data(context: AppContext, plan_id: Any) -> PlanData | None:
    """按 id 回读方案并校验；方案被删/数据损坏都返回 None（追溯断链不猜）。"""
    if not plan_id:
        return None
    row = plans_repo.get(context.conn, str(plan_id))
    if row is None:
        return None
    with contextlib.suppress(Exception):
        return PlanData.model_validate(row["plan_data"])
    return None


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
    payload = selfcheck.run(
        out_path,
        measured_s=media.duration_s,
        has_audio=media.has_audio,
        mode=str(row["narration_mode"] or ""),
        budget_s=None if plan_data is None else _declared_duration_s(plan_data),
        planned_segments=None if plan_data is None else _planned_narration_segments(plan_data),
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
            with contextlib.suppress(Exception):
                if _selfcheck_one(context, export_id):
                    checked += 1
        context.job_store.mark_completed(job_id)
        context.notifier.log("info", f"成片自检完成：{checked}/{total} 条拿到成绩单")
    except Exception as exc:
        context.job_store.mark_failed(job_id, str(exc))
        context.notifier.log("error", f"成片自检批次失败: {exc}")


def delete_export(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """删除一条成片（09-10 §3.4 危险操作规矩）：文件先移入 <data>/.trash/<日期>/ 再删行。

    可恢复性落在文件层：成片与封面都搬（不搬封面就成孤儿），「关于 → 本地数据」
    入口可达 .trash；DB 行硬删（与 project.delete 同先例）。两类失败分开对待：
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
    for key in ("output_path", "cover_path"):
        raw = row.get(key)
        if not raw:
            continue
        path = Path(str(raw))
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
    # 原声段台词字幕的源（批次二）：同一份 asr_segments JSON 的**原始 dict** 视图，
    # 带 text/words（SpeechZone 只有 start/end，是 jitter 保护区的最小形状，不改它）。
    dialogue_items: dict[str, list[dict[str, Any]]] = {}
    # A2 源硬字幕带（避让，不是擦除）：episode_id → (top, bottom) 归一化区间。
    # 与 asr 同一趟预取循环顺带解析（每集一次 get，不逐段查库）；缺集/坏 JSON/
    # 形状不对（非两元素数值对）一律不进缓存 → build_ass 收 None → 现状 margin_v，
    # 逐字节不变。
    subtitle_bands: dict[str, tuple[float, float]] = {}
    for segment in plan_data.timeline:
        episode_id = segment.episode_id
        if episode_id in dialogue_zones:
            continue
        record = analysis_repo.get(context.conn, episode_id)
        if record is None:
            continue
        band_raw = record.get("subtitle_band")
        if band_raw:
            try:
                parsed = json.loads(str(band_raw))
            except (TypeError, json.JSONDecodeError):
                parsed = None
            if (
                isinstance(parsed, list)
                and len(parsed) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in parsed)
            ):
                subtitle_bands[episode_id] = (float(parsed[0]), float(parsed[1]))
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
        chunks = split_subtitle_text(text, line_char_cap(preset, ass_canvas))
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
        ass_path.write_text(
            build_ass(
                lines,
                preset,
                source_band=subtitle_bands.get(
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
        ass_dir = context.work_dir / "export" / export_id
        ass_dir.mkdir(parents=True, exist_ok=True)
        ass_path = ass_dir / f"seg_{segment_index:03d}.ass"
        ass_path.write_text(
            build_ass(lines, preset, source_band=subtitle_bands.get(episode_id), play_res=out_size),
            encoding="utf-8",
        )
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
        out_size=out_size,
        loudness_target=loudness.LoudnessTarget.from_settings(context.settings),
    )
    exports_repo.mark_completed(context.conn, export_id, str(out_path))
    try:
        media = probe.probe(out_path)
        exports_repo.set_meta(
            context.conn, export_id, duration_s=media.duration_s, size_bytes=out_path.stat().st_size
        )
        _audit_duration(context, plan_data, media.duration_s)
    except (ValueError, OSError):
        pass  # 元信息回填/时长审计失败不影响导出成功
    # 四项自检（09-10 #29：导出期产出字段）：增强项绝不挡导出，任何异常都留 NULL
    with contextlib.suppress(Exception):
        _selfcheck_one(context, export_id)
    with contextlib.suppress(OSError, ValueError):
        _extract_cover(
            context,
            export_id,
            out_path,
            title=_cover_title(context, plan_row),
            plan_data=plan_data,
            episode_paths=episode_paths,
            out_size=out_size,
        )  # 封面失败不影响导出成功（源截帧→成片截帧的降级链在 _extract_cover 内）
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
        # 标题先生成再渲染：render_export 尾部的封面字层要用第一条标题，
        # 而 titles 生成不依赖渲染产物（LLM 只吃 plan_data），顺序对调零副作用。
        _ensure_titles(context, run.plan_row)
        out_path = render_export(context, voiced, report=report)
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
