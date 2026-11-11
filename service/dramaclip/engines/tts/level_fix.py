"""干音电平契约：配音进混音链之前把集成响度量进参考带，带外纯增益拉回，峰值归段级限幅。

混音分支让干音以 `volume=1.0` 并入（`amix=normalize=0`），所以它自带的 LUFS 直接决定人声
对原声的比重——这层响度此前无人负责：31 段真缓存干音 −14.8…−11.4 LUFS，换引擎就换 3 dB。

· **参考带 −13.0±1.0 LUFS**：锚＝那 31 段的实测中位；带宽由带外比例实测定（1.5→6%／
  1.0→19%／0.5→42%），再紧一档＝多一倍 mp3 二次有损编码。改这两个数要重新量，别挑。
· **抬升有闸（真峰不得过 −1.0 dBTP）、衰减无闸**：抬增益连底噪一起抬，且重采样与下游
  编码自己会长出 1.1–1.3 dB 采样间过冲。峰值不在这层管——语音频峰比中位 14.3 dB，用
  线性增益压峰必然以人声掉 6.5–9.5 dB 为代价，「限幅空转」与「电平不变」不可兼得。
· **量不到不静默、先验后搬、绝不写回内容寻址缓存**：缓存键里没有电平这一维；每次在
  边界上从缓存原件重做一遍，才不积累世代损失。
"""

from __future__ import annotations

import logging
import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from dramaclip.engines.exporter import loudness
from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg

_LOGGER = logging.getLogger(__name__)

# 锚在 31 段真缓存干音的集成响度中位；换引擎或换语速后重新量。
DRY_LEVEL_TARGET_LUFS = -13.0
DRY_LEVEL_TOLERANCE_DB = 1.0
# 必须留在 0 dBFS 之下：见模块头的采样间过冲那条账。
DRY_LEVEL_HEADROOM_DBTP = -1.0
# 复测判据从带宽推导，不留第二个数。
_RECHECK_TOLERANCE_DB = 2.0 * DRY_LEVEL_TOLERANCE_DB
# 低于这个的增益听不出差别，却要多付一次有损重编码。
_MIN_APPLY_GAIN_DB = 0.05
_TIMEOUT_S = 120.0


@dataclass(frozen=True)
class DryLevelReport:
    """一段干音的电平回执：量到多少、参考带在哪、施加了多少增益、没动或动不了的原因。"""

    source: str
    measured: bool
    before_lufs: float | None = None
    before_dbtp: float | None = None
    after_lufs: float | None = None
    after_dbtp: float | None = None
    applied_gain_db: float = 0.0
    note: str = ""

    def log_line(self) -> str:
        """给管线当留痕用的一行人话：每条出口都说得清「动没动、为什么」。"""
        band = f"{DRY_LEVEL_TARGET_LUFS:.1f}±{DRY_LEVEL_TOLERANCE_DB:.1f}"
        if not self.measured:
            return f"干音电平契约未量到：{self.source} —— {self.note}"
        if self.applied_gain_db == 0.0:
            return (
                f"干音电平未改写：{self.source} I={self.before_lufs:.2f} LUFS"
                f"（参考 {band}）、真峰 {self.before_dbtp:+.2f} dBTP"
                + (f"；{self.note}" if self.note else "")
            )
        return (
            f"干音电平契约：{self.source} I={self.before_lufs:.2f}→{self.after_lufs:.2f} LUFS"
            f"（参考 {band}），施加 {self.applied_gain_db:+.2f} dB，"
            f"真峰 {self.before_dbtp:+.2f}→{self.after_dbtp:+.2f} dBTP"
            + (f"；{self.note}" if self.note else "")
        )


def measure_dry_level(path: Path) -> tuple[float, float]:
    """返回 (LUFS, 真峰 dBTP)；量不出来抛 `loudness.LoudnessError`，不兜底成 0。

    量法直接借门禁/Phase C 那一条命令——同一件事不留第二把尺子。
    """
    proc = subprocess.run(  # noqa: S603
        [resolve_ffmpeg(), *loudness.measure_gate_args(str(path))],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_TIMEOUT_S,
        check=False,
    )
    if proc.returncode != 0:
        raise loudness.LoudnessError(
            f"量响度退出码 {proc.returncode}：{(proc.stderr or '')[-200:]}"
        )
    measurement = loudness.parse_gate_reading(proc.stderr or "")
    return measurement.integrated_lufs, measurement.true_peak_dbtp


def plan_dry_gain(before_lufs: float, before_dbtp: float) -> tuple[float, str]:
    """纯策略：带内不动；带外抬到参考值，抬升被峰值闸钳住；衰减不设闸。

    增益按 LUFS 差算——`volume=dB` 对集成响度是精确位移，不像限幅那样吃包络。
    """
    wanted = DRY_LEVEL_TARGET_LUFS - before_lufs
    if abs(wanted) <= DRY_LEVEL_TOLERANCE_DB:
        return 0.0, ""
    if wanted < 0.0:
        return wanted, ""
    ceiling = DRY_LEVEL_HEADROOM_DBTP - before_dbtp
    if ceiling >= wanted:
        return wanted, ""
    if ceiling <= _MIN_APPLY_GAIN_DB:
        return 0.0, (
            f"真峰 {before_dbtp:+.2f} dBTP 已到抬升闸（不得过 {DRY_LEVEL_HEADROOM_DBTP:+.1f}），"
            f"纯增益够不着参考带，未改写"
        )
    return ceiling, (
        f"抬升被峰值闸钳住：需要 {wanted:+.2f} dB、只施加 {ceiling:+.2f} dB"
        f"（真峰不得过 {DRY_LEVEL_HEADROOM_DBTP:+.1f} dBTP）"
    )


def apply_gain_args(source: str, out_path: str, gain_db: float) -> list[str]:
    """纯增益一遍：容器与采样参数由扩展名/输入决定，这里只碰音量。

    `volume=` 带 `dB` 后缀——裸数字是线性倍率，与滤镜串里压底用的倍率语义不同。
    """
    return [
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        source,
        "-af",
        f"volume={gain_db:.4f}dB",
        "-vn",
        str(out_path),
    ]


def staging_suffix(path: Path) -> str:
    """按**内容**而不是文件名决定暂存容器：识别到 RIFF/WAVE 就走 `.wav`。

    干音文件名统一 `.mp3`，但有的引擎写的是 WAV 字节——跟着文件名走会把无损干音
    转成有损 mp3。这层改的是响度，不是顺手换编码器。
    """
    try:
        with path.open("rb") as handle:
            head = handle.read(12)
    except OSError:
        return path.suffix
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return ".wav"
    return path.suffix


def normalize_dry_level(path: Path) -> DryLevelReport:
    """把一段干音拉进电平参考带，原地替换，返回回执；任何失败都不向外抛。

    带内、闸内抬不动、量不到、增益步炸了——四档都原样交付并把原因写进回执，由调用方
    上屏。一段配音的响度不配把整段判死。
    """
    if not path.is_file() or path.stat().st_size == 0:
        return DryLevelReport(path.name, False, note="干音文件不在或为空，电平契约没量成")
    try:
        before_lufs, before_tp = measure_dry_level(path)
    except (loudness.LoudnessError, subprocess.SubprocessError, OSError) as exc:
        return DryLevelReport(
            path.name, False,
            note=f"量不到电平（{type(exc).__name__}: {exc}），干音按原样进混音链",
        )
    gain_db, note = plan_dry_gain(before_lufs, before_tp)
    if gain_db == 0.0:
        return DryLevelReport(
            path.name, True, before_lufs, before_tp, before_lufs, before_tp, 0.0, note
        )

    staging = path.with_name(
        f"{path.stem}.{uuid.uuid4().hex[:8]}.level{staging_suffix(path)}"
    )
    try:
        proc = subprocess.run(  # noqa: S603
            [resolve_ffmpeg(), *apply_gain_args(str(path), str(staging), gain_db)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TIMEOUT_S,
            check=False,
        )
        if proc.returncode != 0 or not staging.is_file() or staging.stat().st_size == 0:
            return DryLevelReport(
                path.name, True, before_lufs, before_tp, before_lufs, before_tp, 0.0,
                _joined(note, f"增益未产出文件（退出码 {proc.returncode}），干音按原样进混音链"),
            )
        try:
            after_lufs, after_tp = measure_dry_level(staging)
        except (loudness.LoudnessError, subprocess.SubprocessError, OSError) as exc:
            return DryLevelReport(
                path.name, True, before_lufs, before_tp, None, None, 0.0,
                _joined(note, f"产物复测量不到（{type(exc).__name__}: {exc}），保留原干音"),
            )
        # 复测验的是「位移兑现」而不是「逼近参考」：被闸钳住的抬升本来就够不到参考带，
        # 按参考验收会把自己刚批准的产物每次都扔掉，还每段白烧一遍 ffmpeg。
        expected_lufs = before_lufs + gain_db
        if abs(after_lufs - expected_lufs) > _RECHECK_TOLERANCE_DB:
            return DryLevelReport(
                path.name, True, before_lufs, before_tp, after_lufs, after_tp, 0.0,
                _joined(
                    note,
                    f"复测位移不符：预期 {expected_lufs:.2f}、实测 {after_lufs:.2f} LUFS，"
                    "保留原干音",
                ),
            )
        os.replace(staging, path)
    except (loudness.LoudnessError, subprocess.SubprocessError, OSError) as exc:
        return DryLevelReport(
            path.name, True, before_lufs, before_tp, None, None, 0.0,
            _joined(note, f"电平契约未走完（{type(exc).__name__}: {exc}），干音按原样进混音链"),
        )
    finally:
        staging.unlink(missing_ok=True)

    _LOGGER.info(
        "干音电平契约 %s：%+.2f dB → I=%.2f LUFS、真峰 %+.2f dBTP",
        path.name, gain_db, after_lufs, after_tp,
    )
    return DryLevelReport(
        path.name, True, before_lufs, before_tp, after_lufs, after_tp, gain_db, note
    )


def _joined(*parts: str) -> str:
    return "；".join(part for part in parts if part)
