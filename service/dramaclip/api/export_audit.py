"""export 审计族：降级留痕工具（_emit_note/_note_degraded）+ 渲染后与自检度量审计。

自 api/export.py 拆出（拆分专项 A）：留痕与审计是导出域的公共底座，export_covers
与 export 主体单向 import 本模块，本模块不反向依赖同域模块——事后体检与增强项
的留痕死活不许拖垮导出主链。
"""

from __future__ import annotations

import logging
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.engines.exporter import encoder
from dramaclip.engines.narration.models import PlanData
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
