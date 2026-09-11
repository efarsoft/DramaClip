"""Phase C：整片响度归一。

为什么放在拼接之后而不是段内：段内逐段归一会让相邻段之间忽大忽小（响度泵动），
而混音阶段的目标只是"比例正确"（旁白 vs 原声），绝对响度由这一层统一负责。
两遍法（先测后线性归一）是 ffmpeg 官方推荐路径；测完再复核一遍，超差即抛——
静默出一版"响度没到位"的片子等同于降级。
"""

from __future__ import annotations

import json
import os
import re
import subprocess  # noqa: S404 - 参数为受控列表
from dataclasses import dataclass
from pathlib import Path

from dramaclip.infra import config
from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg

_SAMPLE_RATE = 48000
_LRA = 11.0
_TOLERANCE_LU = 2.0  # 复核容差：线性模式受真峰值钳制，允许 2 LU 残差
_TIMEOUT_S = 600.0

_JSON_BLOCK = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


class LoudnessError(RuntimeError):
    """响度链路失败：测不出、近乎无声、或归一后仍偏离目标超容差。"""


@dataclass(frozen=True)
class LoudnessTarget:
    integrated_lufs: float
    true_peak_dbtp: float

    @classmethod
    def from_settings(cls, settings: config.Settings) -> LoudnessTarget:
        return cls(
            integrated_lufs=config.get_float(settings, "export.loudness_target_lufs"),
            true_peak_dbtp=config.get_float(settings, "export.loudness_true_peak_dbtp"),
        )

    def filter(self, **extra: object) -> str:
        params: dict[str, object] = {
            "I": self.integrated_lufs,
            "TP": self.true_peak_dbtp,
            "LRA": _LRA,
        }
        params.update(extra)
        return "loudnorm=" + ":".join(f"{k}={v}" for k, v in params.items())


@dataclass(frozen=True)
class LoudnessMeasurement:
    integrated_lufs: float
    true_peak_dbtp: float
    lra: float
    threshold: float
    target_threshold: float
    # 第一遍 loudnorm 自报的补偿量；两遍法必须回喂，否则第二遍会二次偏移
    offset_lu: float


def measure_args(source: str, target: LoudnessTarget) -> list[str]:
    return [
        "-hide_banner",
        "-nostats",
        "-i",
        source,
        "-map",
        "0:a:0",
        "-af",
        target.filter(print_format="json"),
        "-f",
        "null",
        "-",
    ]


def normalize_args(
    source: str,
    out_path: str,
    target: LoudnessTarget,
    measurement: LoudnessMeasurement,
) -> list[str]:
    return [
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        source,
        "-filter_complex",
        f"[0:a]{target.filter(**{
            'measured_I': measurement.integrated_lufs,
            'measured_TP': measurement.true_peak_dbtp,
            'measured_LRA': measurement.lra,
            'measured_thresh': measurement.threshold,
            'offset': measurement.offset_lu,
            'linear': 'true',
            'print_format': 'summary',
        })}[a]",
        "-map",
        "0:v:0",
        "-map",
        "[a]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        str(_SAMPLE_RATE),
        "-map_metadata",
        "-1",
        "-avoid_negative_ts",
        "make_zero",
        out_path,
    ]


def _parse_number(raw: str, field: str) -> float:
    value = raw.strip().strip('"')
    if value in ("-inf", "inf", "nan"):
        raise LoudnessError(
            f"响度测量 {field} 为 {value}：音轨近乎无声，这样的片子不该交付"
        )
    try:
        return float(value)
    except ValueError as exc:
        raise LoudnessError(f"响度测量 {field} 无法解析：{raw!r}") from exc


def parse_measurements(stderr: str) -> LoudnessMeasurement:
    match = _JSON_BLOCK.search(stderr)
    if match is None:
        raise LoudnessError(f"响度测量未输出 JSON（stderr 尾部：{stderr[-400:]}）")
    data = json.loads(match.group(0))
    missing = [k for k in ("input_i", "input_tp", "input_lra", "input_thresh") if k not in data]
    if missing:
        raise LoudnessError(f"响度测量缺字段：{missing}")
    return LoudnessMeasurement(
        integrated_lufs=_parse_number(str(data["input_i"]), "input_i"),
        true_peak_dbtp=_parse_number(str(data["input_tp"]), "input_tp"),
        lra=_parse_number(str(data["input_lra"]), "input_lra"),
        threshold=_parse_number(str(data["input_thresh"]), "input_thresh"),
        target_threshold=_parse_number(str(data.get("target_thresh", "0")), "target_thresh"),
        offset_lu=_parse_number(str(data.get("offset", "0")), "offset"),
    )


def _run(args: list[str]) -> str:
    proc = subprocess.run(  # noqa: S603
        [resolve_ffmpeg(), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_TIMEOUT_S,
        check=False,
    )
    if proc.returncode != 0:
        raise LoudnessError(f"ffmpeg 退出码 {proc.returncode}：{(proc.stderr or '')[-400:]}")
    return proc.stderr or ""


def normalize_in_place(
    file_path: Path, *, target: LoudnessTarget, work_dir: Path
) -> LoudnessMeasurement:
    """两遍法归一，原地替换 `file_path`，返回归一后的复核实测。"""
    work_dir.mkdir(parents=True, exist_ok=True)
    measurement = parse_measurements(_run(measure_args(str(file_path), target)))
    staged = work_dir / "loudnorm_stage.mp4"
    _run(normalize_args(str(file_path), str(staged), target, measurement))
    if not staged.is_file() or staged.stat().st_size == 0:
        raise LoudnessError("响度归一未产出文件")
    os.replace(staged, file_path)
    checked = parse_measurements(_run(measure_args(str(file_path), target)))
    drift = abs(checked.integrated_lufs - target.integrated_lufs)
    if drift > _TOLERANCE_LU:
        raise LoudnessError(
            f"响度归一后仍偏离目标 {drift:.1f} LU"
            f"（实测 {checked.integrated_lufs:.1f} / 目标 {target.integrated_lufs:.1f}）"
        )
    if checked.true_peak_dbtp > target.true_peak_dbtp + 0.5:
        raise LoudnessError(f"真峰值超标：{checked.true_peak_dbtp:.1f} dBTP")
    return checked
