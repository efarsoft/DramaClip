"""export 审计族：降级留痕工具（_emit_note/_note_degraded）+ 渲染后与自检度量审计。

自 api/export.py 拆出（拆分专项 A）：留痕与审计是导出域的公共底座，export_covers
与 export 主体单向 import 本模块，本模块不反向依赖同域模块——事后体检与增强项
的留痕死活不许拖垮导出主链。
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.engines.exporter import encoder
from dramaclip.engines.narration.models import PlanData
from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.transport import notify as notify_mod

_LOGGER = logging.getLogger(__name__)


def _emit_note(context: AppContext, level: str, message: str) -> None:
    """把一条账面写到**能落的地方**：通知面投递失败就兜进程日志。

    通知面是渲染层的管道，它死了不改变"片已经拼好、账已经算完"这个事实——所以
    事后体检与增强项的留痕一律不许让投递失败反过来改动片的成败。
    """
    try:
        context.notifier.log(level, message)
    except Exception:  # noqa: BLE001 - 通知面故障不是导出失败的理由，日志文件才是底账
        _LOGGER.log(
            logging.INFO if level == "info" else logging.WARNING,
            "%s（通知面投递失败，改记进程日志）", message,
        )


def _note_degraded(
    context: AppContext, subject: str, outcome: str, exc: BaseException | None = None
) -> None:
    """增强项/事后体检没做成时的统一留痕：绝不挡导出，但必须写明丢了什么。

    这些分支原先一律 `contextlib.suppress(Exception)` 或 `pass`——账面干净得像一切
    正常，而「没做成」和「做出来没问题」是两回事（§3.3.1「允许，但必须留痕」）。

    两层账（规格 §1.2）：通知流是实时面（重启即失），**库是真相源**——导出作业
    上下文内追加进 `export_jobs.degraded_notes`，成片卡/队列页事后可读。无作业
    上下文（成片列表重测等旁路调用）只有通知面，如实不落库。
    """
    detail = "" if exc is None else f"：{type(exc).__name__}: {str(exc)[:120]}"
    message = f"{subject}未落地{detail}——{outcome}"
    _emit_note(context, "warn", message)
    _ledger(context, subject, outcome)


def _ledger(context: AppContext, subject: str, outcome: str) -> None:
    """账在库层：作业上下文里 ref_id=export_id 时追加降级账；解析不了就只留通知面。"""
    job_id = notify_mod.current_job_id()
    if not job_id:
        return
    job = context.job_store.get(job_id) if getattr(context, "job_store", None) else None
    if job is None or job.get("type") != "export":
        return
    exports_repo.append_degraded(context.conn, str(job["ref_id"]), subject, outcome)


def _clock_audit(
    cropped: list[dict[str, Any]], win_start: float, dwell_windows: list[tuple[float, float]]
) -> tuple[int, int]:
    """烧录行 vs 字幕驻留窗 → (可对照行数, 与任一驻留窗零重叠的行数)；驻留窗空表记 (0, 0)。

    立案④的可见化：烧录时钟和擦除时钟的关系过去只存在于临时探针脚本里，缺陷跑完也没留痕。
    零重叠行**不等于缺陷**——画外音/纯 ASR 行本就没有屏上对应物：真机库内 10 集 272 行实测
    24 行（8.8%）落在所有驻留窗之外，十集都有。把这条度量当判据就是重演覆盖闸包含式判据
    拦下 8/10 集的老路，所以只记账不拦片。无驻留窗时编码端整段擦，两套时钟无从对照，交
    (0, 0) 让调用方把「可对照 0 行」如实报出来——unknown 不许当成 ok。
    """
    if not dwell_windows:
        return (0, 0)
    stray = 0
    for row in cropped:
        start = win_start + float(row["start"])
        end = win_start + float(row["end"])
        if all(min(end, we) - max(start, ws) <= 0.0 for ws, we in dwell_windows):
            stray += 1
    return (len(cropped), stray)


def _declared_duration_s(plan_data: PlanData) -> float | None:
    """时间轴声明总时长（Σ end-start）；<=0 视为拿不到预算（None，自检该项归灰）。"""
    declared = sum(max(seg.end - seg.start, 0.0) for seg in plan_data.timeline)
    return declared if declared > 0 else None


def _planned_narration_segments(plan_data: PlanData) -> int:
    """方案里的旁白段数（narration/ducked）：自检「含配音」的判据源。"""
    return sum(1 for seg in plan_data.timeline if seg.audio in ("narration", "ducked"))


# 渲染后时长审计的容差不在这里：判据统一由 encoder.AUDIT_DURATION_* 发号
# （dedup 微变速 ±0.4%、切点抖动、AAC/concat 毫秒级出入都在它的预算里），
# 本层只引用——第二处字面量等于第二套判据，改一处就会出现「界面绿、日志 warn」。


def _audit_duration(context: AppContext, plan_data: PlanData, actual_s: float) -> None:
    """实测时长 vs 时间轴声明总时长（sum(end-start)）：超阈值只写 warn 明账。

    审计自身失败不挡导出（它是事后体检），但**不许静默**：测不出来就得写明"这条没核过"
    ——与 `encoder._audit_film_duration` 同规矩。别把两条混为一谈：那条量"成片 vs
    各段实测和"，超线是缺段/拼重，已改判抛错；本条的分母里合法混着保护区外扩，只 warn。
    """
    try:
        declared = sum(max(seg.end - seg.start, 0.0) for seg in plan_data.timeline)
        if declared <= 0:
            return
        diff = actual_s - declared
        # 台词保护区外扩的逐段合法余量（与自检同口径）：快切形态逐段累积可达数秒
        protect_slack = 0.45 * len(plan_data.timeline)
        tolerance = max(
            declared * encoder.AUDIT_DURATION_REL_TOLERANCE,
            encoder.AUDIT_DURATION_ABS_TOLERANCE_S,
            protect_slack,
        )
        if abs(diff) <= tolerance:
            return
        message = (
            f"成片时长审计：实测 {actual_s:.1f}s vs 声明 {declared:.1f}s"
            f"（差 {diff:+.1f}s，超出阈值 ±{tolerance:.1f}s）——成片可能缺段/重复，请人工核对"
        )
    except Exception as exc:  # noqa: BLE001 - 事后体检失败绝不挡已成功的导出
        _note_degraded(context, "成片时长审计", "本条成片的事后核对没有做", exc)
        return
    _emit_note(context, "warn", message)


def _log_clock_audit(context: AppContext, stats: list[tuple[int, int, int]]) -> None:
    """台词时钟对账的出片明账：一条 info，把「烧了几行 / 几行有屏上对应物 / 几行没有」说全。

    判据与不拦片的理由见 `_clock_audit`。三个数一起报，是因为多集拼片可能一部分集有驻留窗、
    一部分没有——只报「烧了几行、几行零重叠」会把没对照的集算进分母（第二处口径）。
    与 `_audit_duration` 同规矩：事后体检失败绝不反过来挡已成功的导出——但**留痕本身不许被吞**，
    算不出来也要把"这条没核过"写出来。"""
    if not any(row_count for row_count, _c, _s in stats):
        return
    try:
        rows = sum(row_count for row_count, _c, _s in stats)
        checked = sum(c for _r, c, _s in stats)
        stray = sum(s for _r, _c, s in stats)
        message = (
            f"台词时钟对账：烧录台词 {rows} 行，可对照 {checked} 行，"
            f"其中 {stray} 行与字幕驻留窗零重叠"
            "——零重叠不等于缺陷（画外音/纯增字幕本无屏上对应物）；可对照 0 行＝该剧无驻留窗"
            "（擦除整段挂），比例升高请核对分析链路"
        )
    except Exception as exc:  # noqa: BLE001 - 对账是事后体检，不许拖垮已成功的导出
        _note_degraded(context, "台词时钟对账", "本条成片的驻留窗重叠没有账面", exc)
        return
    _emit_note(context, "info", message)


# ── 成片静默体检（W6·§6.1 开场 3 秒 + 扩展：结尾 3 秒 / 中段死气段）───────

_SILENCE_THRESHOLD_DB = -50.0
"""麦克风/环境底噪在 −60 以下，−50 是「有内容」与「近似无声」的干净分界（实测）。"""

_SILENCE_DETECT_MIN_S = 1.0
"""silencedetect 的最短静默段：开场/结尾窗口覆盖判的计数单位，再短的网络静音帧不算。"""

_WINDOW_S = 3.0
"""开场/结尾质检窗口：短视频前 3 秒决定划走与否，收尾同理。"""

_WINDOW_COVER = 0.9
"""窗口内静默覆盖率 ≥90% 判无声——判「整段没内容」，不是「均值偏低」。"""

_DEAD_GAP_S = 5.0
"""中段死气门槛：解说话间留白普遍 ≤2s，连续 ≥5s 无声才算节奏塌陷。"""

_DEAD_GAP_REPORT_MAX = 3
"""留痕里最多列出的死气段数：账面要可读，全列交给总数。"""


def _run_silencedetect(output_path: str) -> str:
    """全片 silencedetect 扫描，返回 stderr（ffmpeg 的统计结果走 stderr）。

    一次进程调用喂三条判定（开场/结尾/中段）——逐窗 volumedetect 要三次解码，
    全片扫描只解码一遍。二进制必须走 resolver：打包环境只有随包 ffmpeg、无系统
    PATH，裸命令名每次 FileNotFoundError 会被外层吞成「体检静默永不运行」。
    """
    null_dev = "NUL" if sys.platform == "win32" else "/dev/null"
    # CREATE_NO_WINDOW 是 Windows 独有属性：getattr 姿势过 linux 视角的类型检查
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        [str(resolve_ffmpeg()), "-i", output_path,
         "-af", f"silencedetect=noise={_SILENCE_THRESHOLD_DB:.0f}dB:d={_SILENCE_DETECT_MIN_S}",
         "-f", "null", null_dev],
        capture_output=True, text=True, timeout=120, creationflags=flags, check=False,
    )
    return result.stderr


def _silent_windows(stderr: str, duration_s: float) -> list[tuple[float, float]]:
    """silencedetect 输出 → 静默区间表 [(start, end)]；片尾未闭合的 start 用时长补。

    ffmpeg 对「一直静到片尾」的区间只报 start 不报 end——不补的话结尾判定永远看不见
    片尾静默，而那恰是无声收尾最常见的形态。
    """
    windows: list[tuple[float, float]] = []
    open_start: float | None = None
    for line in stderr.splitlines():
        match = re.search(r"silence_start:\s*(-?[\d.]+)", line)
        if match:
            open_start = float(match.group(1))
            continue
        match = re.search(r"silence_end:\s*(-?[\d.]+)", line)
        if match and open_start is not None:
            end = float(match.group(1))
            if end > open_start:
                windows.append((open_start, end))
            open_start = None
    if open_start is not None and duration_s > open_start:
        windows.append((open_start, duration_s))
    return windows


def _covered_ratio(
    windows: list[tuple[float, float]], start: float, end: float
) -> float:
    """[start, end) 窗口被静默区间覆盖的比例；窗口非法或无重叠记 0。"""
    span = end - start
    if span <= 0:
        return 0.0
    overlap = sum(
        min(w_end, end) - max(w_start, start)
        for w_start, w_end in windows
        if min(w_end, end) > max(w_start, start)
    )
    return min(overlap / span, 1.0)


def _probe_silence_quality(
    context: AppContext, output_path: str, narration_mode: str
) -> None:
    """导出后静默体检三判定：开场 3 秒 / 结尾 3 秒 / 中段死气段。

    解说模式的无声开场是钩子站不住的信号（W6·§6.1）；无声结尾是收尾戛然而止、
    追更转化断在最后一步的信号；中段连续 ≥5s 无声是节奏塌陷。判定都只留痕不拦片，
    与时长审计同纪律。零文案模式（raw_clip 等）原声本就是主体，静默可能是剧情本身，
    不检查。探测自身失败静默跳过——事后体检不许拖垮已成功的导出。
    """
    from dramaclip.api.narration_plans import _NO_TTS_MODES  # noqa: PLC0415 - 延迟导入避免循环

    if narration_mode in _NO_TTS_MODES:
        return
    try:
        duration_s = 0.0
        try:
            from dramaclip.infra.ffmpeg import probe as ffprobe_mod  # noqa: PLC0415

            media = ffprobe_mod.probe(Path(output_path))
            duration_s = float(media.duration_s or 0.0)
        except Exception:  # noqa: BLE001 - 时长拿不到只搁置结尾判定，开场/中段照做
            pass
        windows = _silent_windows(_run_silencedetect(output_path), duration_s)
    except Exception:  # noqa: BLE001 - 事后体检失败绝不挡已成功的导出
        return
    _report_silence_quality(context, windows, duration_s)


def _report_silence_quality(
    context: AppContext, windows: list[tuple[float, float]], duration_s: float
) -> None:
    """三判定装配：每条独立成账，互不屏蔽（开场塌+结尾塌同时存在就该都看见）。"""
    if _covered_ratio(windows, 0.0, _WINDOW_S) >= _WINDOW_COVER:
        _note_degraded(
            context, "开场 3 秒质检",
            f"前 {_WINDOW_S:.0f} 秒近无声（静默覆盖 ≥{_WINDOW_COVER:.0%}，阈值"
            f" {_SILENCE_THRESHOLD_DB:.0f}dB）——钩子可能站不住，建议在方案层重掷此条钩子",
        )
    if duration_s > _WINDOW_S + 1.0:
        tail_start = duration_s - _WINDOW_S
        if _covered_ratio(windows, tail_start, duration_s) >= _WINDOW_COVER:
            _note_degraded(
                context, "结尾 3 秒质检",
                f"末 {_WINDOW_S:.0f} 秒近无声（静默覆盖 ≥{_WINDOW_COVER:.0%}）——"
                "收尾可能戛然而止，追更转化断在最后一步，建议核对成片尾部是否完整",
            )
    interior = [
        (start, end)
        for start, end in windows
        if start >= _WINDOW_S and end - start >= _DEAD_GAP_S
        and (duration_s <= 0 or end <= duration_s - _WINDOW_S)
    ]
    if interior:
        total_s = sum(end - start for start, end in interior)
        shown = "、".join(
            f"{start:.0f}s–{end:.0f}s" for start, end in interior[:_DEAD_GAP_REPORT_MAX]
        )
        more = f" 等 {len(interior)} 处" if len(interior) > _DEAD_GAP_REPORT_MAX else ""
        _note_degraded(
            context, "中段死气段检测",
            f"检出 {len(interior)} 处连续 ≥{_DEAD_GAP_S:.0f}s 无声"
            f"（{shown}{more}，合计 {total_s:.0f}s）——节奏可能塌陷，建议核对剪辑松紧",
        )
