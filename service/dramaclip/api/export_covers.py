"""export 封面与源字幕覆盖族：成品封面截帧 + 源硬字幕覆盖解析 + 原声段台词裁剪。

自 api/export.py 拆出（拆分专项 A）。一族三件事共享同一套底座：①成品封面
（源截帧→成片截帧的降级链，增强项绝不挡导出）；②SubtitleCover 唯一解析处
（渲染预取与出片自检读同一份并集口径）；③原声段台词的词级裁剪与 ass 行装配。
单向依赖 export_audit 的留痕工具，不反向。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from dramaclip.api.context import AppContext
from dramaclip.api.export_audit import _note_degraded
from dramaclip.engines.analysis.models import OcrSegment
from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.subtitle.ass_generator import (
    TRAILING_MARKS,
    coverage_promised,
    split_subtitle_text,
)
from dramaclip.infra.ffmpeg import cover as ffmpeg_cover
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo


def _as_float(value: Any) -> float | None:
    """JSON 里的时间戳 → float；不是数就 None（坏行逐个跳过，不炸整段渲染）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _dwell_windows(raw: Any) -> list[tuple[float, float]]:
    """episode_analysis.ocr_segments → 台词在屏上的驻留窗（源绝对秒）。

    给编码端把 delogo 收窄成「只在有字的那几秒挂」（2026-10-09 业主裁决③）。
    逐条走 `OcrSegment` 校验：非 JSON、非列表、元素形状不对、区间倒挂一律丢弃，
    全丢光就是空表——空表在编码端等于「不收窄，整段擦」，坏数据不会让源字幕
    漏擦（漏擦=原片台词留在屏上，是可见缺陷）。
    """
    if not raw:
        return []
    try:
        items = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(items, list):
        return []
    windows: list[tuple[float, float]] = []
    for item in items:
        try:
            bar = OcrSegment.model_validate(item)
        except ValidationError:
            continue
        if bar.end > bar.start:
            windows.append((float(bar.start), float(bar.end)))
    return windows


def _as_pair(raw: Any) -> tuple[float, float] | None:
    """两元素数值对 → (float, float)；形状不对（含 bool）一律 None。"""
    if (
        isinstance(raw, list)
        and len(raw) == 2
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in raw)
    ):
        return (float(raw[0]), float(raw[1]))
    return None


@dataclass(frozen=True)
class SubtitleCover:
    """一集的源硬字幕覆盖数据（`episode_analysis` 三列的解析结果）。

    渲染预取和出片后自检读的是同一份数据、同一个并集口径——两处各解析一遍就是
    第二处真相源，「成绩单说盖住了」和「字幕实际盖住了」从此对不上号。
    """

    band: tuple[float, float] | None = None
    line_rects: tuple[tuple[float, float], ...] = ()
    dwell_windows: tuple[tuple[float, float], ...] = ()

    @property
    def cover_rect(self) -> tuple[float, float] | None:
        """压位与擦除共同跟随的目标矩形：采信行框的**并集**优先，行框缺失才回退整带包络。

        擦除用逐行框（贴行不贴带），定位也必须用同一批框的并集——整带含
        `_BAND_EXPAND` 上下各 4% 的描边余量、还可能比台词实际占位宽得多，跟它走
        中心就偏（2026-10-09 真机第6集：带 (0.600,0.930) 里台词只在 (0.809,0.903)，
        按包络压位把字放到了脸上）。跨行台词的并集中心落在两行共同的中间，
        正是覆盖语义要的位置。
        """
        if not self.line_rects:
            return self.band
        return (min(rect[0] for rect in self.line_rects), max(rect[1] for rect in self.line_rects))


def _subtitle_cover(record: dict[str, Any]) -> SubtitleCover:
    """`episode_analysis` 行 → 覆盖数据（带 / 采信行框 / 台词驻留窗）的唯一解析处。

    A2 源硬字幕带（覆盖，不是避让：擦掉源字再把我们的字放回原位）：subtitle_band 两种
    落库格式都认——新 = dict（band + lines），旧 = 纯 list（band）。缺字段/坏 JSON/
    形状不对一律不进结果 → 消费端收 None/空 → 现状 margin_v、整段擦，逐字节不变。

    存量行框再夹两次：① 共享形状谓词——旧数据里可能混着花字/道具行
    （2026-10-07 审计：ep1 花字卡、ep9 招幌曾被当台词行落库），也混着两行合并成的
    高框（ep6 存量 0.619-0.772 h=0.153 糊下半张脸）；② 台词带内位置闸。判据与生产者
    `_cluster_lines` 同一处发号。
    """
    band: tuple[float, float] | None = None
    rects: tuple[tuple[float, float], ...] = ()
    band_raw = record.get("subtitle_band")
    if band_raw:
        try:
            parsed = json.loads(str(band_raw))
        except (TypeError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, dict):
            band = _as_pair(parsed.get("band"))
            raw_lines = parsed.get("lines")
            if band is not None and isinstance(raw_lines, list):
                from dramaclip.engines.analysis.subtitle_ocr import (
                    line_in_dialogue_band,
                    line_is_caption_row,
                )

                rects = tuple(
                    rect
                    for item in raw_lines
                    if (rect := _as_pair(item)) is not None
                    and line_is_caption_row(rect)
                    and line_in_dialogue_band(rect, band)
                )
        else:
            band = _as_pair(parsed)
    return SubtitleCover(
        band=band,
        line_rects=rects,
        dwell_windows=tuple(_dwell_windows(record.get("ocr_segments"))),
    )


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
    except Exception as exc:  # noqa: BLE001 - 增强项失败退回无字层截帧
        _note_degraded(context, "封面字层标题", "封面出无字层", exc)
        return None


def _cover_source_frame(
    conn: Any,
    plan_data: PlanData,
    episode_paths: dict[str, str],
    out_size: tuple[int, int],
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
    # 封面选帧（VL 主线 2026-10-28）：从 visual_track 找首段时窗内 watch_score
    # 最高的帧的时刻，不再固定 1.5s——「情绪最炸的那一帧」才是好封面。
    # 无画面轨/无 watch_score 回退 1.5s（旧行为）。
    seek_s = first.start + 1.5
    composition = (
        f"scale={out_size[0]}:{out_size[1]}:force_original_aspect_ratio=decrease,"
        f"pad={out_size[0]}:{out_size[1]}:(ow-iw)/2:(oh-ih)/2:color=black"
    )
    if conn is not None:
        try:
            analysis = analysis_repo.get(conn, str(first.episode_id))
            if analysis is not None and analysis.get("visual_track"):
                vt = json.loads(str(analysis["visual_track"]))
                best_s, best_w = None, 0
                for frame in vt.get("frames") or []:
                    w = int(frame.get("watch_score") or 0)
                    ft = float(frame.get("t") or 0)
                    if first.start - 1e-6 <= ft <= first.end + 1e-6 and w > best_w:
                        best_w = w
                        best_s = float(frame.get("t") or 0)
                if best_s is not None:
                    seek_s = round(best_s, 3)
        except (json.JSONDecodeError, TypeError, KeyError, ValueError):
            pass  # 坏数据回退固定偏移
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
            source_frame = _cover_source_frame(context.conn, plan_data, episode_paths, out_size)
        except Exception as exc:  # noqa: BLE001 - 增强项自诊断失败也退回成片截
            _note_degraded(context, "源素材截帧", "封面改从成片截（画面带烧录字幕）", exc)
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


def crop_dialogue_lines(
    items: list[dict[str, Any]], win_start: float, win_end: float
) -> list[dict[str, Any]]:
    """把库内 ASR 句按段切割窗口 [win_start, win_end] 裁成段内台词行（批次二）。

    返回元素形状 {start, end, text, words}：start/end 是**重定基到窗口起点的相对秒**，
    words 是同基的词表（[{start,end,word}]）或 None（句级降级）。

    词级裁剪（FunClip 的多数重叠思路）：跨界词按「与窗口的重叠 ≥ 词长一半」归属——
    一半以上音节落在段内，观众就能在本段听到它，字幕跟声音走；恰好压线归本段
    （前半在本段听得到，后半切掉了也要把词标出来，否则台词缺字）。

    双时钟归一（2026-10-10 立案④）：行窗（item 的 start/end，=融合行的字幕驻留窗，编码端
    擦除读的同一个数）是**唯一显示时钟**；词戳只定「哪几个词属于本段」和行内节奏，不直接
    决定字在屏上出现的时刻。所以归属前先把该行词戳区间整体仿射贴合到行窗
    （`[词戳跨度起点, 词戳跨度终点] → [s, e]`），行内比例保留、绝对位置换成字幕窗。
    旧实现两套时钟并用：真机 ep1 实测中位差 3.80s、最大 13.34s，23 行里 16 行的烧录时刻与
    源字幕窗重叠为 0（源字幕在屏时我们的字不在），整行词戳全落段外时台词整行消失。

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
            span0 = min(entry["ws"] for entry in valid_words)
            span1 = max(entry["we"] for entry in valid_words)
            scale = (e - s) / (span1 - span0)
            kept: list[dict[str, Any]] = []
            for entry in valid_words:
                ws = s + (entry["ws"] - span0) * scale
                we = s + (entry["we"] - span0) * scale
                wt = entry["wt"]
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


def _plan_cover_promise(
    context: AppContext, plan_data: PlanData | None
) -> tuple[float, float] | None:
    """这条片子的**覆盖承诺**：时间轴涉及各集 cover_rect 的并集，只收生成端真承诺的形状。

    自检的画面侧度量拿它当基准。判据与渲染端同源：同一处解析（`_subtitle_cover`）、
    同一个承诺定义（`ass_generator.coverage_promised`）。多集异画幅把并集撑成误检形状
    时返回 None（那一项归灰）——宁灰，不冤枉成红。
    """
    if plan_data is None:
        return None
    rects: list[tuple[float, float]] = []
    for episode_id in dict.fromkeys(segment.episode_id for segment in plan_data.timeline):
        record = analysis_repo.get(context.conn, str(episode_id))
        if record is None:
            continue
        rect = _subtitle_cover(record).cover_rect
        if rect is not None and coverage_promised(rect):
            rects.append(rect)
    if not rects:
        return None
    union = (min(rect[0] for rect in rects), max(rect[1] for rect in rects))
    return union if coverage_promised(union) else None


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
