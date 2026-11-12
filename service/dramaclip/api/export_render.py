"""导出渲染编排：ExportRun → render_export（剪辑→字幕→编码→自检→封面）。

自 api/export.py 拆出（拆分专项）：渲染编排是 export RPC 外壳下的真实业务——
`_run_export`（留在 export.py）投递 ExportRun，render_export 跑完它。拆出后
export.py 回归 RPC 外壳（submit/retry/list/delete/publish_report），本模块
承载渲染执行体与它的全部依赖。

与 export.py 的依赖单向：本模块**延迟导入** export._selfcheck_one（render_export
尾部调用，函数体内 import 防环）；export.py 模块级导入本模块的 render_export /
ExportRun / _needs_voice / _ensure_voiced / _ensure_titles / _cleanup_export_segments。
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.api.export_audit import (
    _audit_duration,
    _clock_audit,
    _emit_note,
    _log_clock_audit,
    _note_degraded,
    _probe_silence_quality,
)
from dramaclip.api.export_covers import (
    SubtitleCover,
    _cover_title,
    _dialogue_ass_lines,
    _subtitle_cover,
    crop_dialogue_lines,
)
from dramaclip.api.voice_prep import (  # noqa: F401 - re-export 供 api/export.py 打桩直呼
    _VOICE_NEEDED_ENGINES as _VOICE_NEEDED_ENGINES,
)
from dramaclip.api.voice_prep import (
    _ensure_clone_voice as _ensure_clone_voice,
)
from dramaclip.api.voice_prep import (
    _ensure_titles as _ensure_titles,
)
from dramaclip.api.voice_prep import (
    _ensure_voiced as _ensure_voiced,
)
from dramaclip.api.voice_prep import (
    _needs_voice as _needs_voice,
)
from dramaclip.engines.analysis.models import SpeechZone
from dramaclip.engines.bgm import library as bgm_library
from dramaclip.engines.bgm import selector as bgm_selector
from dramaclip.engines.exporter import (
    ai_label,
    aigc_metadata,
    drama_name_layer,
    encoder,
    loudness,
)
from dramaclip.engines.narration import pipeline as narration_pipeline
from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.semantic import llm_budget
from dramaclip.engines.subtitle import presets as subtitle_presets
from dramaclip.engines.subtitle.ass_generator import (
    Canvas,
    build_ass,
    line_char_cap,
    split_subtitle_text,
)
from dramaclip.engines.subtitle.srt import SrtCue, format_srt
from dramaclip.infra import compute, config
from dramaclip.infra.ffmpeg import probe
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import bgm as bgm_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.rpc import RpcDomainError

# ---------------------------------------------------------------------------
# 常量与工具
# ---------------------------------------------------------------------------


def _safe_filename(name: str) -> str:
    """项目名 → 安全文件名段（去除路径/非法字符）。"""
    forbidden = "\\/:*?\"<>|"
    cleaned = "".join(ch for ch in name.strip() if ch not in forbidden)
    return cleaned.replace(" ", "_")[:40] or "project"


# 渲染遍 AIGC 守卫（retry/排队竞态同拒）：见 render_export 入口
_ERR_AIGC_CONFIG = -32411
_AIGC_MISSING_PRODUCER_MSG = (
    "AIGC 隐式标识已开启但未填写服务提供者编码：请在设置「出片」分区填写"
    "（全国人工智能生成合成内容标识服务平台注册获取），或关闭隐式标识开关"
)


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


# ---------------------------------------------------------------------------
# 渲染输入装配
# ---------------------------------------------------------------------------


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


def _write_film_map(
    context: AppContext,
    out_path: Path,
    film_map: list[dict[str, float | int | str]] | None,
) -> None:
    """成片↔源实测对照边车（.filmmap.json）：avsync/ending 自检的刻度来源。

    声明时间轴不含 jitter/保护区/atempo，互相关映射与词级出点检查吃它失真；
    渲染层实测对照落边车，重测（不再有内存里的 offsets）也能用同一刻度。
    量不到不落盘（旧片回退声明映射=旧行为）；成片删除移 .trash 时边车可能
    残留——只读产物，残留无害。
    """
    if not film_map:
        return
    try:
        out_path.with_suffix(".filmmap.json").write_text(
            json.dumps(film_map, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as exc:
        _note_degraded(context, "成片对照边车", "自检将回退声明时间轴（精度降级）", exc)


def _load_film_map(out_path: Path) -> list[dict[str, float | int | str]] | None:
    sidecar = out_path.with_suffix(".filmmap.json")
    if not sidecar.is_file():
        return None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, list) and data else None


def _film_ending_of(
    context: AppContext,
    plan_data: PlanData | None,
    film_map: list[dict[str, float | int | str]] | None = None,
) -> tuple[float | None, list[tuple[float, float, str]] | None]:
    """成片最后一刀的源切点与该集台词句表（结尾出点检查的数据面）。

    取**最后一个原声段**：旁白/CTA 收尾不切源素材，词级出点对它无意义。
    film_map（批5）：有实测对照边车时出点用渲染层记录的 jitter 后安全窗
    终点——声明 end 与实际末刀差 ±0.3s+，词级判 mid_line 的精度被它吞掉。
    集无分析记录/无台词 → (None, None)，检查归灰。
    """
    if plan_data is None:
        return None, None
    originals = [seg for seg in plan_data.timeline if seg.audio == "original"]
    if not originals:
        return None, None
    last = originals[-1]
    ending_episode, ending_end = str(last.episode_id), float(last.end)
    if film_map:
        actual = [
            rec for rec in film_map if str(rec.get("audio")) == "original"
        ]
        if actual:
            ending_episode = str(actual[-1].get("episode_id") or ending_episode)
            ending_end = float(actual[-1].get("source_end") or ending_end)
    record = analysis_repo.get(context.conn, ending_episode)
    if record is None:
        return None, None
    lines = [
        (float(a.start), float(a.end), str(a.text))
        for a in narration_pipeline.parse_asr_segments(
            str(record.get("asr_segments") or "")
        )
    ]
    return ending_end, lines or None


# ---------------------------------------------------------------------------
# BGM 床选曲
# ---------------------------------------------------------------------------

_VL_MOOD_TO_BGM: dict[str, str] = {
    "紧张": "suspense", "惊悚": "suspense", "压迫": "suspense", "恐惧": "suspense",
    "愤怒": "anger", "暴怒": "anger", "仇恨": "anger",
    "胜利": "triumph", "爽": "triumph", "热血": "triumph", "畅快": "triumph", "狂喜": "triumph",
    "悲伤": "sadness", "痛苦": "sadness", "绝望": "sadness", "心酸": "sadness", "崩溃": "sadness",
}


def _vl_dominant_mood(context: AppContext, plan_data: PlanData) -> str | None:
    """VL 画面轨 mood 众数 → BGM 情绪键；无数据/映射不足半数返回 None（不硬校准）。"""
    moods: list[str] = []
    for eid in sorted({str(seg.episode_id) for seg in plan_data.timeline}):
        record = analysis_repo.get(context.conn, eid)
        if record is None or not record.get("visual_track"):
            continue
        try:
            vt = json.loads(str(record["visual_track"]))
        except (json.JSONDecodeError, TypeError):
            continue
        for frame in vt.get("frames") or []:
            mood = str(frame.get("mood") or "").strip()
            if mood:
                moods.append(mood)
    if len(moods) < 3:
        return None
    mapped = [m for m in moods if m in _VL_MOOD_TO_BGM]
    if len(mapped) < len(moods) / 2:
        return None
    from collections import Counter
    return Counter(mapped).most_common(1)[0][0]


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
    # BGM 情绪校准（T2 VL 主线）：VL 画面轨 mood 众数覆盖台词情绪——观众看到
    # 什么就配什么。无画面数据回退台词情绪。
    vl_mood_emotion = _vl_dominant_mood(context, plan_data)
    track = bgm_selector.select_bgm(plan_data, tracks, emotion_override=vl_mood_emotion)
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


# ---------------------------------------------------------------------------
# 渲染核心
# ---------------------------------------------------------------------------


def render_export(
    context: AppContext,
    run: ExportRun,
    *,
    report: Callable[[float, str], None],
    job_id: str | None = None,
) -> Path:
    """渲染核心：剪辑→字幕→编码→写成品记录（失败抛异常，不管理 job）。
    """
    # 渲染遍自守提供者编码（审查 Important#1）：retry 不经 submit、排队期间编码也可能
    # 被清空——凡开启而编码空，构造 aigc_stamp 之前硬失败，绝不静默交付法定无效标。
    if aigc_metadata.missing_producer(context.settings):
        raise RpcDomainError(_ERR_AIGC_CONFIG, _AIGC_MISSING_PRODUCER_MSG)
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
    offsets_emitted: list[Sequence[dict[str, float | int | str]]] = []
    # 渲染核心全本地 ffmpeg：预算冻结计时（只计等云端响应的时间）
    with llm_budget.paused():
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
            # 剧名常驻层（业主裁决 2026-11-09：默认关、用户可开）：剧名取项目名。
            burn_drama_name=(
                project_name if drama_name_layer.enabled(context.settings) else None
            ),
            compute_sink=reports.append,
            encoder_requested=codec_setting,
            segment_offsets_sink=offsets_emitted.append,
            # BGM 床（C 项接线）：设置/模式/曲库三层门禁在 _pick_bgm 内，任一层不过
            # 返回 None＝现状出片。混音失败在 encoder 层向上抛，这里降级留痕不挡导出。
            bgm_track=_pick_bgm_track(context, plan_data),
            # AIGC 隐式标识（业主裁决 2026-11-09：默认关、用户可开）：内容编号用 export_id，
            # 与回流账同一标识符；编码非空由本函数入口的渲染遍守卫保证（retry/排队竞态同拒）。
            aigc_stamp=(
                (aigc_metadata.producer_code(context.settings), export_id)
                if aigc_metadata.enabled(context.settings)
                else None
            ),
        )
    # 清洗在前、编码在后：读账的人按时间顺序看（规格 §3.5）
    receipt = [*run.voice_reports, *(item.to_dict() for item in reports)]
    exports_repo.set_compute(context.conn, export_id, receipt)
    if job_id is not None:
        context.job_store.set_compute(job_id, receipt)
    _log_clock_audit(context, clock_stats)
    exports_repo.mark_completed(context.conn, export_id, str(out_path))
    film_map = list(offsets_emitted[-1]) if offsets_emitted else None
    _write_film_srt(
        context, out_path, burned_lines,
        {int(rec["seq"]): float(rec["film_start"]) for rec in film_map}
        if film_map
        else None,
    )
    _write_film_map(context, out_path, film_map)
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
        from dramaclip.api.export import _selfcheck_one  # noqa: PLC0415 - 延迟导入防环
        _selfcheck_one(context, export_id)
    except Exception as exc:  # noqa: BLE001 - 自检失败不许把已拼好的片拖成失败
        _note_degraded(context, "导出期四项自检", "成绩单留 NULL，可在成片列表重测", exc)
    try:
        from dramaclip.api.export import _extract_cover  # noqa: PLC0415 - 延迟导入防环
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


def _cleanup_export_segments(context: AppContext, export_id: str) -> None:
    """导出成功后收走段文件（长跑稳定性④）：seg_*.mp4 + concat.txt 占大头，
    留着没有复用价值（成片已交付、sig 签名供断点续跑判定保留）。
    清理失败不挡成功——磁盘上多留几 GB 比误报导出失败好。
    """
    import shutil as _shutil

    work = context.work_dir / "export" / export_id
    try:
        if not work.is_dir():
            return
        removed = 0
        freed = 0
        for item in work.iterdir():
            if item.name.startswith("seg_") and item.suffix == ".mp4":
                freed += item.stat().st_size
                item.unlink(missing_ok=True)
                removed += 1
            elif item.name.endswith(".concat.txt"):
                item.unlink(missing_ok=True)
        # bgm/loudness 中间件目录也一并收
        for subdir in ("bgm", "loudnorm"):
            child = work / subdir
            if child.is_dir():
                _shutil.rmtree(child, ignore_errors=True)
        if removed > 0:
            context.notifier.log(
                "info", f"导出工作目录清理：收走 {removed} 个段文件（{freed // 1024 // 1024}MB）"
            )
    except OSError:
        pass  # 清理是增强不是义务

