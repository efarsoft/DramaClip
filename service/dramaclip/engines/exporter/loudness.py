"""Phase C：整片响度归一。

为什么放在拼接之后而不是段内：段内逐段归一会让相邻段之间忽大忽小（响度泵动），
而混音阶段的目标只是"比例正确"（旁白 vs 原声），绝对响度由这一层统一负责。
两遍法（先测后归一）是 ffmpeg 官方推荐路径；测完再复核一遍，超差即抛——
静默出一版"响度没到位"的片子等同于降级。

归一方式：我们**要求**线性（`linear=true`，纯增益、不动动态），但 loudnorm 只在两个条件
同时成立时才肯走线性——`0 < measured_LRA ≤ LRA`，且 `measured_TP + (I − measured_I) ≤ TP`
（即素材 crest ≤ `TP − I`：按门限值 −1.5 是 12.5 dB，按本模块多要的 `_TP_ENCODE_HEADROOM_DB`
即 −2.5 只剩 11.5 dB）；任一不满足它自己退回 dynamic（LRA 压缩 + 真峰限制）。
也就是说：**线性是偏好，dynamic 是常态，本模块不得对"线性"作任何承诺。**
真机实测（8.1.1-essentials，仓里 9 部 Phase C 之前的真成片，crest 10.2–17.8 dB）：
按 −1.5 要 TP 时 8 部里 7 linear / 1 dynamic，按 −2.5 要时只剩 3 linear / 5 dynamic，
分界与上面那条不等式逐部吻合。dynamic 在安静段落上可能听出泵动，但它照样打得到目标响度
（同一批实测偏离 0.03–1.01 LU），而且这正是 loudnorm 该有的取舍。
"""

from __future__ import annotations

import json
import os
import re
import subprocess  # noqa: S404 - 参数为受控列表
from dataclasses import dataclass
from pathlib import Path

from dramaclip.infra import config
from dramaclip.infra.ffmpeg import probe
from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg

_SAMPLE_RATE = 48000
_LRA = 11.0
_TOLERANCE_LU = 2.0  # 复核容差：dynamic 受真峰值钳制打不满目标，实测残差 0.03–1.09 LU
_TIMEOUT_S = 600.0

# 真峰值的两笔预算，改任一个都必须同时复核另一个（tests 把这对关系钉死了）。
#
# `_TP_ENCODE_HEADROOM_DB`：**滤镜侧多要的余量**。loudnorm 在滤镜内部按 192 kHz 限真峰，
# 之后 192k→48k 重采样 + AAC 编码会再抬出一截采样间过冲，而复核门限量的是抬过之后的值。
# 真机实测（8.1.1-essentials，14 个滤镜自报 `output_tp=-1.50` 即被限峰的源）：编码后落在
# −1.50 … −0.64 dBTP，过门的那批里**最差只剩 0.08 dB 余量**（−1.08 对门限 −1.0），
# 两个高 crest（LRA 0.2–0.3、crest 14.2 / 14.7 dB）源直接超标，整条导出硬失败
# （`真峰值超标：-0.8 dBTP` / `真峰值超标：-0.6 dBTP`）。
#
# `_TP_GATE_MARGIN_DB`：**门限侧放的余量**。放宽它只是把编码器过冲藏起来，不解决问题；
# 余量必须在滤镜侧先要出来。
_TP_ENCODE_HEADROOM_DB = 1.0
_TP_GATE_MARGIN_DB = 0.5

_JSON_BLOCK = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)

# 真机键集（9 部真成片 + 20 个合成源逐源比对，完全一致）：
#   input_i, input_tp, input_lra, input_thresh, output_i, output_tp, output_lra,
#   output_thresh, normalization_type, target_offset
# 计划原稿写的 `target_thresh` / `offset` 两个键 ffmpeg 从不输出。
_REQUIRED_KEYS = (
    "input_i",
    "input_tp",
    "input_lra",
    "input_thresh",
    # 下面两个是"改键名要响"的守卫，比取到什么值更要紧：
    # `target_offset` 是两遍法的回喂量，用 .get(..., "0") 兜住就等于静默 0.0——
    # 响度没归一还照常出片，而且测试照绿（本模块落地时正是这样坏的）。
    # `output_thresh` 我们不消费（loudnorm 没有目标阈值这个输入项），守它只为同一件事。
    "output_thresh",
    "target_offset",
)


class LoudnessError(RuntimeError):
    """响度链路失败：测不出、近乎无声、无音轨、或归一后仍偏离目标超容差。"""


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
    # 第一遍 loudnorm 自报的补偿量（真键名 `target_offset`）；两遍法必须回喂，
    # 否则第二遍会二次偏移。真机实测：丢掉它之后最差的一个源偏离目标 5.7 LU（回喂后 0.55 LU）。
    offset_lu: float


def measure_args(source: str, target: LoudnessTarget) -> list[str]:
    """测量遍（两遍法的第一遍，也是归一后的复核遍）。

    **不得加 `-loglevel`**：loudnorm 的 JSON 打在 `AV_LOG_INFO` 上。真机实测同一条命令
    只换 `-loglevel`——不带该旗标 → JSON 在；`info` → 在；`warning` → 没了；`error` → 没了；
    四种情况 ffmpeg 都 exit 0。而下面的 `normalize_args` 恰恰**要**带 `-loglevel error`，
    所以"把两处弄一致"的重构会让 Phase C 全线量不出响度，全套字符串断言却一条不红。
    """
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
            # 真峰值按 target−1.0 要，不是按 target 要：滤镜在 192 kHz 内限峰，
            # 之后重采样 + AAC 还会抬出采样间过冲，而复核门限量的是抬过之后的值。
            # 实测数字与"为什么不去放宽门限"见 _TP_ENCODE_HEADROOM_DB。
            'TP': target.true_peak_dbtp - _TP_ENCODE_HEADROOM_DB,
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
        # 192k 是真峰值门限的一部分，不是可以随手优化的码率旋钮：同素材同滤镜换成 128k，
        # 编码后真峰 −1.40→−0.67 / −1.35→−0.82 / −1.08→−0.15 dBTP，192k 下过门的三条全超标。
        # 顺带把账认下来（Fix F7）：段级音轨本来就是 AAC 128k，这里解码再编一次，
        # 是货真价实的第二次有损代。整片归一没有别的走法（响度只能对整片量），
        # 而 128k→192k 的听感差异可忽略。
        "-b:a",
        "192k",
        # 必须显式落回 48k。loudnorm 走 dynamic 时内部工作在 192 kHz，不指定 `-ar` 的话
        # ffmpeg exit 0 并静默写出 `aac, sample_rate=96000`（降到 AAC 合法上限）——
        # 96k 对短视频平台非标准，也破坏本仓"全段 48k"的不变量（concat 流复制按首段
        # 采样率解读全部包）。真机实测：**这个坑只在 dynamic 素材上出现**（crest 13.7 /
        # 14.2 / 17.8 dB 三部去掉 -ar → 96000），linear 素材仍是 48000（线性模式不升采样，
        # crest 6.6 dB 那部实测如此）——素材相关，所以它一直没被发现。
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
    missing = [k for k in _REQUIRED_KEYS if k not in data]
    if missing:
        raise LoudnessError(f"响度测量缺字段：{missing}")
    return LoudnessMeasurement(
        integrated_lufs=_parse_number(str(data["input_i"]), "input_i"),
        true_peak_dbtp=_parse_number(str(data["input_tp"]), "input_tp"),
        lra=_parse_number(str(data["input_lra"]), "input_lra"),
        threshold=_parse_number(str(data["input_thresh"]), "input_thresh"),
        offset_lu=_parse_number(str(data["target_offset"]), "target_offset"),
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
    """两遍法归一，原地替换 `file_path`，返回归一后的复核实测。

    复核量的是 staged 产物，通过了才 `os.replace` 落地：反过来做的话，一次"真峰值超标"
    抛错之后成品路径上已经躺着一版能播的超标片——库里写着 failed、`list_works` 也不显示它，
    是最难查的那种不一致。
    """
    # 事前判无音轨，别等 ffmpeg 报 `Stream map '' matches no streams`（退出码 -22 的无符号
    # 回绕 4294967274）：运维看不懂那句话。可达路径是 `cut_segment_args` 的 else 分支把音频
    # 写成可选映射（`-map 0:a:0?`），无音轨源集 → 无音轨段 → 无音轨成片。
    # 用探测而不是匹配 ffmpeg 的报错文本：文本随版本/语言变，探测结果是结构化的。
    # 行为变更：Phase C 之前无音轨成片是静默交付的，现在硬失败（近乎无声的片子不该交付）。
    if not probe.probe(file_path).has_audio:
        raise LoudnessError(f"成片没有音轨，无法归一响度：{file_path.name}")
    work_dir.mkdir(parents=True, exist_ok=True)
    measurement = parse_measurements(_run(measure_args(str(file_path), target)))
    staged = work_dir / "loudnorm_stage.mp4"
    _run(normalize_args(str(file_path), str(staged), target, measurement))
    if not staged.is_file() or staged.stat().st_size == 0:
        raise LoudnessError("响度归一未产出文件")
    checked = parse_measurements(_run(measure_args(str(staged), target)))
    drift = abs(checked.integrated_lufs - target.integrated_lufs)
    if drift > _TOLERANCE_LU:
        raise LoudnessError(
            f"响度归一后仍偏离目标 {drift:.1f} LU"
            f"（实测 {checked.integrated_lufs:.1f} / 目标 {target.integrated_lufs:.1f}）"
        )
    if checked.true_peak_dbtp > target.true_peak_dbtp + _TP_GATE_MARGIN_DB:
        raise LoudnessError(f"真峰值超标：{checked.true_peak_dbtp:.1f} dBTP")
    os.replace(staged, file_path)
    return checked
