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

from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg

# 与 verify_modes.py 同源的阈值初值（那边 L75-76；时长容差与 api/export.py 的
# _AUDIT_DURATION_* 同判据——自检的「时长达标」就是渲染后时长审计的产品化）。
MIN_MEAN_VOLUME_DB = -70.0
MAX_FREEZE_S = 2.0
DURATION_REL_TOLERANCE = 0.08
DURATION_ABS_TOLERANCE_S = 3.0

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


def check_duration(measured_s: float | None, budget_s: float | None) -> dict[str, Any]:
    """时长达标：实测 vs Σ 时间轴声明时长，阈值 max(8%, 3s)（与 _audit_duration 同判）。

    budget 拿不到（方案已删/时间轴为空）或实测拿不到都归 null——「—」，不猜。
    """
    if measured_s is None or budget_s is None or budget_s <= 0:
        return {"pass": None}
    tolerance = max(budget_s * DURATION_REL_TOLERANCE, DURATION_ABS_TOLERANCE_S)
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


_ITEMS = ("duration", "narration", "silence", "freeze")


def overall_state(checks: dict[str, Any]) -> str:
    """汇总态（selfcheck_state 列的词表）：passed=四项全绿 / failed=任一红 / partial=其余。

    partial 覆盖「有灰项且无红项」的全部组合（含四项全 null）：量不全的片子
    不冒充通过，也不冤枉成失败。
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
) -> dict[str, Any]:
    """四项全测，返回落库形状的成绩单（json.dumps 后进 export_jobs.selfcheck）。

    measured_s/has_audio 来自调用方已有的 probe 结果（零额外成本）；解码测量
    只有 mean_volume 与冻结帧两项，合并一遍。
    """
    mean_volume_db, max_freeze_s = measure_audio_video(video)
    payload = {
        "version": 1,
        "checked_at": _now_ms(),
        "duration": check_duration(measured_s, budget_s),
        "narration": check_narration(has_audio, mode, planned_segments),
        "silence": check_silence(mean_volume_db, has_audio),
        "freeze": check_freeze(max_freeze_s),
    }
    return payload
