"""成片自检四项（09-10 §4.5 / 接口改动点 #29）：时长达标 · 含配音 · 无静音段 · 无长冻结帧。

判据从 scripts/verify_modes.py 逐字搬来（阈值 -70dB / 2.0s / max(8%,3s) 同源，
spec §10 开放项 1 写明是初值、未做真人校准），但身份不同：那边是全链路真机回归
门禁，这边是**逐片体检成绩单**——结果只落库供徽章显示，绝不挡导出、不改状态。

诚实纪律：任何一项量不到就写 pass=null（徽章灰「—」，宁灰勿假绿）；量到了
不过线才写 false（红 ✕ 带实测数）；量到了过线才是 true（绿勾）。未验证的东西
不能发通行证，所以「没测」与「测过没问题」必须是两种视觉。

成本纪律：mean_volume（volumedetect）与最长冻结帧（freezedetect）合并进
**一遍解码**（同一条 -f null 命令挂两个滤镜），导出任务尾部只多付一次整片
解码；时长与含配音两项零解码成本（复用既有 probe 结果与方案行）。
"""

from __future__ import annotations

import re
import subprocess  # noqa: S404 - 参数为受控列表
import time
from pathlib import Path
from typing import Any

from dramaclip.engines.analysis import subtitle_ocr
from dramaclip.engines.exporter import encoder
from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg

# 与 verify_modes.py 同源的阈值初值（那边 L83-84）；时长容差不在此定义——
# 自检的「时长达标」就是渲染后时长审计的产品化，判据由 encoder.AUDIT_DURATION_* 发号。
MIN_MEAN_VOLUME_DB = -70.0
MAX_FREEZE_S = 2.0

# freezedetect 参数与 verify_modes.max_freeze_s 逐字同判：噪声门 -60dB、
# 只报 >=1.0s 的静止段；「无长冻结帧」的线在 MAX_FREEZE_S。
_FREEZE_VF = "freezedetect=n=-60dB:d=1.0"
_MEAN_VOLUME_RE = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")
_FREEZE_DURATION_RE = re.compile(r"freeze_duration:\s*(\d+(?:\.\d+)?)")

# 含配音判定的模式表（verify_modes.EXPECT_NARRATION 原样）：none=本就无旁白的
# 模式，有音轨即算过；one/many 还要求方案时间轴里真有下限条数的旁白段——
# 光有音轨不够，那可能是纯原声顶替了解说。
EXPECT_NARRATION: dict[str, str] = {
    "raw_clip": "none",
    "highlight_cut": "none",
    "subtitle_flow": "none",
    "intro_narration": "one",
    "cross_narration": "many",
    "ultra_short_hook": "many",
    "dialogue_narration": "many",
    "full_narration": "many",
    "dual_host_chat": "many",
    "inner_monologue": "many",
}
_NARRATION_FLOOR = {"one": 1, "many": 2}
# 台词保护区外扩的逐段合法余量：safe_times 避字外移 + 尾垫，单段 ≤0.45s
# （±0.3s 挪移 + 台词尾 +0.15s）。逐段累积对快切形态不可忽略。
_SEGMENT_PROTECT_SLACK_S = 0.45


def _now_ms() -> int:
    return int(time.time() * 1000)


def measure_audio_video(
    video: Path, *, timeout_s: float = 900.0
) -> tuple[float | None, float | None]:
    """一遍解码测 (mean_volume_db, max_freeze_s)；量不到的那项为 None。

    与 verify_modes 的两条单项命令参数逐字一致，只是合进同一遍（volumedetect
    挂音频、freezedetect 挂视频，同写 -f null）。`-map 0:a:0?` 的可选映射保证
    无音轨文件不会让整条命令失败——那时 mean_volume 缺行解析为 None，冻结帧
    照常可测。命令跑不起来/解码失败给 (None, None)：这是「量不到」，不是
    「静音/冻结」的判定，两项各归 null 灰。
    """
    try:
        completed = subprocess.run(  # noqa: S603
            [
                resolve_ffmpeg(),
                "-hide_banner",
                "-nostats",
                "-i",
                str(video),
                "-map",
                "0:v:0",
                "-vf",
                _FREEZE_VF,
                "-map",
                "0:a:0?",
                "-af",
                "volumedetect",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    if completed.returncode != 0:
        return None, None
    mean_match = _MEAN_VOLUME_RE.search(completed.stderr)
    mean_volume_db = float(mean_match.group(1)) if mean_match is not None else None
    freezes = [float(value) for value in _FREEZE_DURATION_RE.findall(completed.stderr)]
    # 命令成功而没有任何 freeze_duration 行 = 真的没测出静止段，是 0.0 不是缺测
    return mean_volume_db, max(freezes, default=0.0)


def check_duration(
    measured_s: float | None,
    budget_s: float | None,
    *,
    segment_count: int = 0,
) -> dict[str, Any]:
    """时长达标：实测 vs Σ 时间轴声明时长，阈值 max(8%, 3s)（与 _audit_duration 同判）。

    `segment_count` 提供时按段追加**台词保护区外扩余量**（每段 ≤0.45s：切点避字
    会合法外移，逐段累积对快切形态不可忽略——真机 highlight 14 段累计 +5.5s
    曾被误判时长不达标）。预算与余量都拿不到（方案已删/时间轴为空）或实测
    拿不到都归 null——「—」，不猜。
    """
    if measured_s is None or budget_s is None or budget_s <= 0:
        return {"pass": None}
    tolerance = max(
        budget_s * encoder.AUDIT_DURATION_REL_TOLERANCE,
        encoder.AUDIT_DURATION_ABS_TOLERANCE_S,
        segment_count * _SEGMENT_PROTECT_SLACK_S,
    )
    return {
        "pass": abs(measured_s - budget_s) <= tolerance,
        "measured_s": round(measured_s, 2),
        "budget_s": round(budget_s, 2),
        "tolerance_s": round(tolerance, 2),
    }


def check_narration(has_audio: bool, mode: str, planned_segments: int | None) -> dict[str, Any]:
    """含配音：音轨存在是底线；解说类模式还要求方案里真有旁白段（floor 同 verify_modes）。"""
    expected = EXPECT_NARRATION.get(mode, "many")
    if expected == "none":
        return {"pass": has_audio, "has_audio": has_audio, "expected": expected}
    if planned_segments is None:
        # 解说类却查不到方案（被删/校验失败）：底线项量得出、判据项量不出，归 null
        return {"pass": None, "has_audio": has_audio, "expected": expected}
    floor = _NARRATION_FLOOR.get(expected, 2)
    return {
        "pass": has_audio and planned_segments >= floor,
        "has_audio": has_audio,
        "expected": expected,
        "planned_segments": planned_segments,
    }


def check_silence(mean_volume_db: float | None, has_audio: bool) -> dict[str, Any]:
    """无静音段：整片 mean_volume ≥ -70dB。无音轨 = 整片皆静音，直接红（这不是缺测）。"""
    if not has_audio:
        return {"pass": False, "reason": "无音轨"}
    if mean_volume_db is None:
        return {"pass": None}
    return {"pass": mean_volume_db >= MIN_MEAN_VOLUME_DB, "mean_volume_db": mean_volume_db}


def check_freeze(max_freeze_s: float | None) -> dict[str, Any]:
    """无长冻结帧：最长静止段 < 2.0s（verify_modes 用 >= 判红，此处取其反面）。"""
    if max_freeze_s is None:
        return {"pass": None}
    return {"pass": max_freeze_s < MAX_FREEZE_S, "max_freeze_s": max_freeze_s}


# 成片文字落位的容差：承诺带半高 + 这一项。OCR 框贴着字面走，量的是墨迹不是盒，
# 描边/阴影带来的边界抖动取 2% 画面高（≈38px@1920）——再小就被抽帧采样噪声吃掉。
_CAPTION_CENTER_TOL = 0.02


def measure_caption_band(
    video: Path,
    *,
    work_dir: Path,
    duration_s: float,
    ocr: subtitle_ocr.OcrCallable | None = None,
) -> tuple[float, float] | None:
    """成片里 OCR 到的台词文字带（top/bottom 占成片高）；量不到给 None。

    直接复用分析层那条探测线（10 探针帧投票），不另造一套判据。OCR 依赖没装、
    抽帧失败、成片确实一个字都没有——一律 None：那是「量不到」，不是「落位错」。
    """
    try:
        return subtitle_ocr.detect_band(
            video, work_dir, duration_s=duration_s, ocr=ocr
        )
    except Exception:  # noqa: BLE001 - 画面侧度量绝不炸掉整张成绩单
        return None


def check_caption_placement(
    measured: tuple[float, float] | None,
    expected: tuple[float, float] | None,
) -> dict[str, Any]:
    """画面侧那一项：成片实测的文字中心，盖在承诺覆盖的源台词带上吗。

    与出片前的静态闸分工不同：闸在 ASS 里反解每一行的墨迹区间（事前、逐行、
    漂了不出片），这里量的是**成品像素**（事后）——所以 scale/pad/delogo/
    letterbox 折算这些「生成端算对了但画面被后续环节挪走」的形状才有数。

    判据 `|实测中心 - 承诺中心| ≤ 承诺带半高 + _CAPTION_CENTER_TOL`：中心落在带内
    （含抖动余量）就算盖住，**贴边也算**。承诺由调用端按 `coverage_promised` 过滤后
    才传进来，这里不再判形状——两处判据会漂。四个 top/bottom 与两个长度项都是**画面高
    占比**（不是秒，故不带 `_s` 后缀；`cover_tolerance` 与时长项的 `tolerance_s`
    不同单位）。
    """
    if expected is None:
        return {"pass": None, "reason": "无覆盖承诺"}
    if measured is None:
        return {"pass": None, "reason": "成片文字未量到"}
    measured_center = (measured[0] + measured[1]) / 2
    expected_center = (expected[0] + expected[1]) / 2
    # 判定读成绩单里那三个小数：结论必须能从记录复算出来，否则观众会看到
    # 「两个数一模一样却判红」。差值本来就只精确到千分高（≈2px@1920），
    # 先四舍五入再比，不改变任何真实结论，只让「贴边算盖住」这条线可验证。
    center_offset = round(measured_center - expected_center, 3)
    cover_tolerance = round((expected[1] - expected[0]) / 2 + _CAPTION_CENTER_TOL, 3)
    return {
        "pass": abs(center_offset) <= cover_tolerance,
        "measured_top": round(measured[0], 3),
        "measured_bottom": round(measured[1], 3),
        "expected_top": round(expected[0], 3),
        "expected_bottom": round(expected[1], 3),
        "center_offset": center_offset,
        "cover_tolerance": cover_tolerance,
    }


_ITEMS = ("duration", "narration", "silence", "freeze")


def overall_state(checks: dict[str, Any]) -> str:
    """汇总态（selfcheck_state 列的词表）：passed=四项全绿 / failed=任一红 / partial=其余。

    partial 覆盖「有灰项且无红项」的全部组合（含四项全 null）：量不全的片子
    不冒充通过，也不冤枉成失败。

    `caption_placement` 刻意不在 `_ITEMS` 里：四项是既有交付徽章的口径，画面侧
    那一项是这一批新加的实测，红不该把一张「四项全绿」的成绩单整体改色——它自己
    有徽章位置呈现。
    """
    flags = [checks[name]["pass"] for name in _ITEMS]
    if any(flag is False for flag in flags):
        return "failed"
    if all(flag is True for flag in flags):
        return "passed"
    return "partial"


def run(
    video: Path,
    *,
    measured_s: float | None,
    has_audio: bool,
    mode: str,
    budget_s: float | None,
    planned_segments: int | None,
    segment_count: int = 0,
    caption_band: tuple[float, float] | None = None,
    work_dir: Path | None = None,
) -> dict[str, Any]:
    """四项全测 + 画面侧落位实测，返回落库形状的成绩单（json.dumps 后进 export_jobs.selfcheck）。

    measured_s/has_audio 来自调用方已有的 probe 结果（零额外成本）；解码测量
    只有 mean_volume 与冻结帧两项，合并一遍。

    `caption_band` 是调用端按 `coverage_promised` 过滤后的**覆盖承诺**（源台词带）：
    只有真承诺了才付成片 OCR 的账（10 探针帧），没承诺/没 work_dir 直接灰，不猜。
    """
    mean_volume_db, max_freeze_s = measure_audio_video(video)
    measured_caption: tuple[float, float] | None = None
    if caption_band is not None and work_dir is not None and measured_s:
        measured_caption = measure_caption_band(
            video, work_dir=work_dir, duration_s=measured_s
        )
    payload = {
        "version": 1,
        "checked_at": _now_ms(),
        "duration": check_duration(
            measured_s, budget_s, segment_count=segment_count
        ),
        "narration": check_narration(has_audio, mode, planned_segments),
        "silence": check_silence(mean_volume_db, has_audio),
        "freeze": check_freeze(max_freeze_s),
        "caption_placement": check_caption_placement(measured_caption, caption_band),
    }
    return payload
