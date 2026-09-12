"""Phase C：整片响度归一。

为什么放在拼接之后而不是段内：段内逐段归一会让相邻段之间忽大忽小（响度泵动），
而混音阶段的目标只是"比例正确"（旁白 vs 原声），绝对响度由这一层统一负责。

**两条路，优先走确定性那条**：先按门禁的量法（`ebur128=peak=true`）量一次整片，
如果"纯增益就够到目标响度、且加完真峰仍在滤镜要的余量之内"，就走 `volume=<gain>dB`
加一道前瞻限幅当安全网（`gain_normalize_args`）；只有素材**真的需要动态压缩**才落回
两遍 loudnorm（`normalize_args`）。为什么这么排：loudnorm 的 dynamic 模式在短素材上
不收敛——真机实测 15.2 s 的 `ultra_short_hook_2c9b87` 归一后残差 3.2 LU（实测 −17.2 /
目标 −14.0）——而纯增益是确定性的、不泵动，15 s 和 200 s 一视同仁。
两条路都打不到规格就抛，不许静默出一版"响度没到位"的片子（等同于降级）。

本轮真机复验（8.1.1-essentials，`data/outputs` 的隔离副本，全部走真 `normalize_in_place`、
用门禁那条 ebur128 命令验收）：
15.32 s 的真成片 `ultra_short_hook_67ee9c` 走 **gain 路**，连跑两次分别出来
`I=−12.80 / TP=−1.10` 与 `I=−13.80 / TP=−2.10`，两次都在门限内（容差 2.0 LU、门限 −1.0 dBTP）；
同一部片子走改动前那条 loudnorm-only 算法**两次都失败、而且两次错在不同地方**
（`真峰值超标 −0.4 dBTP（重试后仍超）` / `偏离目标 2.0 LU（自报 −16.0）`）——
连失败方式都不复现，根因见 `parse_gate_reading` 里那条"最后一块自己就不稳定"的实测。
15.2 s 的合成短片（I=−20.50 / crest 8.90 dB）走 gain 路出来 **`I=−14.00`，偏离 0.00 LU**
——纯增益就是算术，短片长片一个样。
反过来，209.7 s 的真成片 `intro_narration_275746`（I=−9.80 / TP=+3.20 / crest 13.0 dB）
判据落在 **loudnorm 路**，有界重试之后仍 `真峰值超标 −0.3 dBTP` 硬失败——
**增益路救不了它，也不该救**：它要的是上游别把 +3.2 dBTP 的削顶带进成片
（段级真峰天花板，`encoder.py` 那一侧的账），响度这层继续按规格响。
同类的 `intro_narration_325c84`（197.9 s，crest 13.0）走 loudnorm 路 + 一次真峰重试过门
（`I=−14.00 / TP=−2.30`），说明重试那一档仍然有效。

量法为什么换成 ebur128：门禁（`scripts/verify_modes.py`）判红绿用的就是它，而 loudnorm
自报的 `input_i` 是另一套实现，同一部片子实测差 0.2 LU。更要紧的是**音轨中途换声道布局
时 loudnorm 会吐两块 JSON**（成因与实测数字见 `parse_measurements` 的注释），
两套解析器各取一块，Phase C 与门禁量的就不是同一段音频。

loudnorm 那条路（保留原样）：两遍法（先测后归一）是 ffmpeg 官方推荐路径；测完再复核一遍，
超差即抛。唯一例外：**真峰**复核超标允许换更大滤镜余量重试一次（AAC 过冲对所请求 TP
不单调，见 `_TP_RETRY_HEADROOM_DB`）；integrated 偏差不重试。

归一方式：我们**要求**线性（`linear=true`，纯增益、不动动态），但 loudnorm 只在两个条件
同时成立时才肯走线性——`0 < measured_LRA ≤ LRA`，且 `measured_TP + (I − measured_I) ≤ TP`
（即素材 crest ≤ `TP − I`：按门限值 −1.5 是 12.5 dB，按本模块多要的 `_TP_ENCODE_HEADROOM_DB`
即 −2.5 只剩 11.5 dB）；任一不满足它自己退回 dynamic（LRA 压缩 + 真峰限制）。
也就是说：**线性是偏好，dynamic 是常态，本模块不得对"线性"作任何承诺。**
（注意第二条不等式与上面"走不走增益路"的判据是同一个：`measured_TP + gain ≤ 滤镜 TP`。
差别在我们自己算增益时不受 `0 < measured_LRA ≤ LRA` 约束、也不受 loudnorm 内部 192 kHz
工作格式影响，所以能覆盖一部分 loudnorm 会退回 dynamic 的素材。）
真机实测（8.1.1-essentials，仓里 9 部 Phase C 之前的真成片，crest 10.2–17.8 dB）：
按 −1.5 要 TP 时 8 部里 7 linear / 1 dynamic，按 −2.5 要时只剩 3 linear / 5 dynamic，
分界与上面那条不等式逐部吻合。dynamic 在安静段落上可能听出泵动，但它照样打得到目标响度
（同一批实测偏离 0.03–1.01 LU），而且这正是 loudnorm 该有的取舍。
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess  # noqa: S404 - 参数为受控列表
from dataclasses import dataclass
from pathlib import Path

from dramaclip.infra import config
from dramaclip.infra.ffmpeg import probe
from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg

_LOGGER = logging.getLogger(__name__)

_SAMPLE_RATE = 48000
_LRA = 11.0
_TOLERANCE_LU = 2.0  # 复核容差：dynamic 受真峰值钳制打不满目标，实测残差 0.03–1.09 LU
_TIMEOUT_S = 600.0

# 门禁那套量法，与 `scripts/verify_modes.py::ebur128` 逐字一致。`framelog=quiet` 只为压掉
# 逐帧行（同一部片子实测 stderr 544 行 → 42 行），Summary 照打。
_EBUR128_AF = "ebur128=peak=true:framelog=quiet"

# 真峰值的三笔预算，改任一个都必须同时复核其余（tests 把首遍那对关系钉死了）。
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
#
# `_TP_RETRY_HEADROOM_DB`：**真峰复核超标后重试一次的滤镜余量**。为什么必须重试而不是
# 把首遍余量直接调大：过冲对所请求的 TP **不单调**。真机实测（8.1.1-essentials，
# `intro_narration_325c84` 真成片）按滤镜 TP=−1.5/−2.0/−2.25/−2.5/−2.75/−3.0/−3.5 逐个重编，
# 过冲 0.12/0.96/0.87/**1.68**/0.99/0.71/0.66 dB——−2.5（首遍：目标 −1.5 减 1.0）正踩谐振点，
# 编码后 −0.82 dBTP 超门限；−3.0 可过（integrated 偏离仅 0.06 LU）。任何固定余量都不可能被
# 证明对任意素材够用，所以：**首遍按 1.0 dB 要（对绝大多数素材够用、响度代价最小），
# 复核专因真峰超标时换 1.5 dB 从原始成片重编一次；再超标就抛**。只重试一次：过冲不单调，
# 更长的梯子在证明力上并不比实测选出的这一步强，而每次重试都是整片重编的分钟级代价；
# 打不到的目标必须响，不许循环到成功为止。integrated 偏离超容差**不重试**——
# 那是电平问题，多要余量救不了，重试只会掩盖真缺陷。
_TP_ENCODE_HEADROOM_DB = 1.0
_TP_GATE_MARGIN_DB = 0.5
_TP_RETRY_HEADROOM_DB = 1.5

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


def filter_true_peak_ask(
    target: LoudnessTarget, headroom_db: float = _TP_ENCODE_HEADROOM_DB
) -> float:
    """向滤镜要的真峰天花板 = 目标真峰 − 编码过冲预算（三笔预算的实测见常量注释）。

    做成函数而不是在三处各写一遍减法：**这三个数必须是同一个数**——
    `normalize_args` 向 loudnorm 要的 TP、`gain_normalize_args` 里 alimiter 的 limit、
    `normalize_in_place` 判"纯增益够不够"的可行性判据。判据说的是"加完增益真峰落在 X 以内，
    所以不用压缩"，安全网就必须真的钉在 X 上；两边各算各的话，判据批准的东西没人执行，
    要等到复核才发现，而复核不过的代价是整片重编（甚至整条导出失败）。
    `headroom_db` 只有真峰重试那一处会传别的值（`_TP_RETRY_HEADROOM_DB`）。
    """
    return target.true_peak_dbtp - headroom_db


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
    """loudnorm 两遍法的第一遍（只为拿 `measured_*` 与 `target_offset` 回喂第二遍）。

    复核遍不用它，用 `measure_gate_args`（门禁量法）。

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


def measure_gate_args(source: str) -> list[str]:
    """决策遍与复核遍：与 `scripts/verify_modes.py::ebur128` **逐字同一条命令**。

    为什么必须同一条：门禁的红绿就是本模块的验收线。两套量法同一部片子实测差 0.2 LU，
    而门禁窗口只比生产容差松 0.5 LU——量法一岔开，"Phase C 说过了、门禁说没过"就会常有。

    **同样不得加 `-loglevel`**：ebur128 的 Summary 与 loudnorm 的 JSON 一样打在
    `AV_LOG_INFO` 上。真机实测（8.1.1-essentials，同一条命令只换该旗标）：
    不带 → 1 块 Summary；`info` → 1 块；`warning` → **0 块**；`error` → **0 块**；
    四种情况 ffmpeg 都 exit 0。
    """
    return [
        "-hide_banner",
        "-nostats",
        "-i",
        source,
        "-map",
        "0:a:0",
        "-af",
        _EBUR128_AF,
        "-f",
        "null",
        "-",
    ]


# ebur128 的 Summary 版式（真机捕获，见 tests/engines/exporter/test_loudness.py 的
# `_EBUR128_ONE`）：三节，每节标题以冒号结尾，`Threshold:` 在 integrated 与 LRA 两节里
# 各出现一次——所以必须**按节**取，靠"第一个 Threshold"会拿到 -34.6 那一行的值。
_GATE_SECTIONS = ("Integrated loudness", "Loudness range", "True peak")
_GATE_WANTED = {
    ("Integrated loudness", "I"): "I",
    ("Integrated loudness", "Threshold"): "threshold",
    ("Loudness range", "LRA"): "LRA",
    ("True peak", "Peak"): "Peak",
}


def parse_gate_reading(stderr: str) -> LoudnessMeasurement:
    """解析 ebur128 的 Summary；**多块时取最后一块**，与门禁的解析器同判。

    为什么会有多块（真机实测，`ultra_short_hook_2c9b87`）：这部成片的音轨**中途换了声道
    布局**——ffprobe 逐帧数，前 177 帧 mono（0…3.787687 s）、后 533 帧 stereo。ffmpeg 于是
    在 3.79 s 处打印 `Reconfiguring filter graph because audio parameters changed to
    48000 Hz, stereo, fltp`，测量滤镜被 flush（打出第一块 Summary），新建的实例量剩下的
    11.4 s（EOF 时打出第二块）。loudnorm 因此也吐两块 JSON（见 `parse_measurements`）。
    实测任何 `-af` 都触发（连 `anull` 也 reconfig=1），前置 `aformat=channel_layouts=stereo`
    压不住（依旧 2 块）；只有先解码成 WAV 再量才是 0 reconfig / 1 块。

    **两块都不是整片**：第一块 I=-21.4/Peak=-5.4 是片头 3.79 s，第二块 I=-8.9/Peak=+1.9
    是剩下 11.4 s（整片解码成 stereo WAV 实测 I=-8.5/Peak=+0.4，与第二块吻合）。
    取最后一块不是因为"更对"，而是因为**门禁取的是最后一块**（它的循环后值覆盖前值），
    Phase C 必须与门禁判同一段音频。根因（段级声道布局不统一）记在 plan 的 Task 8 里。

    **这么取的代价，本轮量到了底**：同类的 `ultra_short_hook_67ee9c`（15.32 s，ffprobe 逐帧
    184 帧 mono + 533 帧 stereo）上，同一条命令连跑 5 次，最后一块的 I 依次是
    **-7.8 / -8.0 / -8.8 / -8.1 / -9.0 LUFS（极差 1.2 LU）**，Peak 五次都是 +1.3，
    第一块五次都是 -27.5。整片解码成 WAV 再量（0 reconfig / 1 块）是 I=-11.0 / Peak=+0.3，
    即最后一块把整片响度高估了约 2 LU，而且**它自己就不复现**。
    所以决策读数只能当**预测**、不能当结论：验收线是复核（产物声道布局均匀，1 块，
    连量三次逐位相同），预测失准就退回 loudnorm 路一次（见 `normalize_in_place`）。
    门禁读的是同一个不稳定的数——这不是本模块能单独修的，根因在段级声道布局不统一。

    `offset_lu` 恒为 0.0：ebur128 没有 target_offset 这个概念，那个字段只对 loudnorm
    两遍法的回喂有意义（见 `LoudnessMeasurement`），复核结果里没人消费它。
    """
    chunks = stderr.split("Summary:")
    if len(chunks) < 2:
        raise LoudnessError(f"ebur128 未输出 Summary（stderr 尾部：{stderr[-400:]}）")
    found: dict[str, str] = {}
    section = ""
    for line in chunks[-1].splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.rstrip(":") in _GATE_SECTIONS and stripped.endswith(":"):
            section = stripped.rstrip(":")
            continue
        key, sep, rest = stripped.partition(":")
        if not sep:
            continue
        want = _GATE_WANTED.get((section, key.strip()))
        if want is not None and rest.strip():
            found[want] = rest.strip().split()[0]
    missing = [name for name in ("I", "Peak", "LRA", "threshold") if name not in found]
    if missing:
        raise LoudnessError(
            f"ebur128 Summary 缺字段：{missing}（stderr 尾部：{stderr[-400:]}）"
        )
    return LoudnessMeasurement(
        integrated_lufs=_parse_number(found["I"], "I"),
        true_peak_dbtp=_parse_number(found["Peak"], "Peak"),
        lra=_parse_number(found["LRA"], "LRA"),
        threshold=_parse_number(found["threshold"], "Threshold"),
        offset_lu=0.0,
    )


def normalize_args(
    source: str,
    out_path: str,
    target: LoudnessTarget,
    measurement: LoudnessMeasurement,
    *,
    headroom_db: float = _TP_ENCODE_HEADROOM_DB,
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
            # 真峰值按 target−headroom 要，不是按 target 要：滤镜在 192 kHz 内限峰，
            # 之后重采样 + AAC 还会抬出采样间过冲，而复核门限量的是抬过之后的值。
            # 首遍 headroom=_TP_ENCODE_HEADROOM_DB；真峰复核超标后的那一次重试按
            # _TP_RETRY_HEADROOM_DB 要（实测数字与"为什么不去放宽门限"见两常量的注释）。
            'TP': filter_true_peak_ask(target, headroom_db),
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


def gain_normalize_args(
    source: str, out_path: str, target: LoudnessTarget, gain_db: float
) -> list[str]:
    """确定性增益路：`volume=<gain>dB` + 一道前瞻限幅当安全网。

    为什么优先它（真机实测，`ultra_short_hook_2c9b87`，15.2 s）：loudnorm 的 dynamic 模式
    在这么短的素材上不收敛，归一后残差 **3.2 LU**（实测 −17.2 / 目标 −14.0），整条导出硬失败。
    纯增益是算术，15 s 和 200 s 一视同仁，也不泵动。同一部片子实测走增益路（gain=−5.10 dB）
    之后 `I=−13.9 LUFS / Peak=−1.4 dBFS`，两项都进窗口。

    `dB` 后缀**不可省**：ffmpeg 的 `volume` 不带后缀时把值当**线性增益因子**读。真机实测
    `volume=-12.0` 是"乘 −12 倍"（即 +21.6 dB 反相放大），同一张素材出来
    `I=−8.4 LUFS / Peak=+21.0 dBFS`——想衰减 12 dB 结果猛推了 21 dB。

    后面那道 alimiter 是**安全网**，不是第二级归一：天花板取 `target_TP − _TP_ENCODE_HEADROOM_DB`
    （默认 −2.5 dBTP → 线性 0.7499），与 loudnorm 路向滤镜要的真峰同一个数。
    `level=disabled` 必须显式给——alimiter 的 `level` 默认 true，会按 1/limit 把输出抬回去
    （自动电平），那就把 Task 7 刚消灭的归一化从后门放回来了；真机实测 0 dBFS 正弦过
    `limit=0.7079`：默认参数 `max_volume 0.0 dB`，`level=disabled` 才是 `-3.0 dB`。
    **本路自己的实测**（15.2 s 床音、limit=0.7499）：删掉 `level=disabled` 之后增益产物
    被凭空抬 +2.50 dB 到 `I=-11.50`，偏离 2.50 LU 超容差 → 复核驳回 → 退回 loudnorm 路重编，
    交付的片子**照样是 -14.00 LUFS**。也就是说响度数字本身看不出增益路已经废了
    （每部片子白编一遍、短素材又回到 dynamic 不收敛那条路上），只有留痕能看出来——
    这条账记在 `test_gain_branch_hits_the_target_on_real_audio` 的"没走退路"断言里。
    `latency=true` 补掉前瞻带来的 4.98 ms 音画错位。

    编码外壳与 `normalize_args` 同一套（视频流复制、AAC 192k、显式落回 48k、擦元数据、
    时间戳归零），两笔账（192k 与 -ar）的理由见那边的注释，这里不重复也不得各改各的。
    """
    ceiling_db = filter_true_peak_ask(target)
    limiter = (
        f"alimiter=limit={10 ** (ceiling_db / 20):.4f}:level=disabled:latency=true"
    )
    return [
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        source,
        "-filter_complex",
        f"[0:a]volume={gain_db:.4f}dB,{limiter}[a]",
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
    """解析 loudnorm 的 JSON；**多块时取最后一块**，与 `parse_gate_reading` 同一个规矩。

    为什么会有两块（真机实测，`ultra_short_hook_2c9b87`，15.2 s）：成片音轨中途换了声道
    布局（ffprobe 逐帧：前 177 帧 mono、后 533 帧 stereo），ffmpeg 在 3.79 s 处
    `Reconfiguring filter graph because audio parameters changed to 48000 Hz, stereo, fltp`，
    loudnorm 实例被 flush（吐出第一块 JSON）、新实例量剩下的 11.4 s（EOF 吐第二块）。
    两块实测：第一块 `input_i=-21.47 / input_tp=-5.39 / input_lra=0.00`（片头 3.79 s），
    第二块 `input_i=-9.59 / input_tp=+1.88 / input_lra=8.70`（剩下 11.4 s，与九模式门禁
    记下的 −9.58/+1.88 对得上）。

    原先这里用 `.search()` 取**第一块**，等于拿片头 3.79 s 的读数去归一整部 15.2 s 的片子
    ——两遍法的 `measured_*` 全错，这正是"响度归一后仍偏离目标 3.2 LU"的成因之一。
    取最后一块与门禁同判（门禁的 ebur128 解析器是后值覆盖前值）。诚实记账：两块**都不是
    整片**，根因是段级声道布局不统一（混音段被 amix 收成 mono、原声直通段跟着源走 stereo，
    concat 流复制把两种布局拼进了同一条流），已记进 plan 的 Task 8 实测修正。
    """
    blocks = _JSON_BLOCK.findall(stderr)
    if not blocks:
        raise LoudnessError(f"响度测量未输出 JSON（stderr 尾部：{stderr[-400:]}）")
    data = json.loads(blocks[-1])
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


def _measure_staged(staged: Path) -> LoudnessMeasurement:
    """复核 staged 产物，用**门禁那套量法**（ebur128）。"""
    if not staged.is_file() or staged.stat().st_size == 0:
        raise LoudnessError("响度归一未产出文件")
    return parse_gate_reading(_run(measure_gate_args(str(staged))))


def normalize_in_place(
    file_path: Path, *, target: LoudnessTarget, work_dir: Path
) -> LoudnessMeasurement:
    """归一整片响度，原地替换 `file_path`，返回归一后的复核实测（门禁量法）。

    先用门禁的 `ebur128=peak=true` 量一次，再决定走哪条路：

    * **gain 路**——纯增益就够到目标、且加完真峰仍在滤镜要的余量之内
      （`measured_TP + (target_I − measured_I) ≤ target_TP − _TP_ENCODE_HEADROOM_DB`）。
      确定性、不泵动、15 s 的短片一样收敛。
    * **loudnorm 路**——素材是真需要动态压缩才塞得下，保留原两遍法与它的有界真峰重试。

    复核量的是 staged 产物，通过了才 `os.replace` 落地：反过来做的话，一次"真峰值超标"
    抛错之后成品路径上已经躺着一版能播的超标片——库里写着 failed、`list_works` 也不显示它，
    是最难查的那种不一致。

    gain 路的复核没过就**退回 loudnorm 路一次**（有界）：那条判据是拿测量读数算的预测，
    而预测会失准（真机实测两例：真峰差 1.8 dB；响度差 1.20 LU 且真峰差 2.60 dB，
    理由与数字见下面的注释）。两条路都打不到规格才抛。
    loudnorm 路内部：真峰复核超标允许**一次**重试（换 `_TP_RETRY_HEADROOM_DB` 从原始成片
    重编），因为 AAC 过冲对所请求的滤镜 TP 不单调，首遍可能纯属踩点；integrated 偏离
    超容差不重试，直接抛——那是电平问题，多要余量救不了，重试只会掩盖真缺陷。
    """
    # 事前判无音轨，别等 ffmpeg 报 `Stream map '' matches no streams`（退出码 -22 的无符号
    # 回绕 4294967274）：运维看不懂那句话。可达路径是 `cut_segment_args` 的 else 分支把音频
    # 写成可选映射（`-map 0:a:0?`），无音轨源集 → 无音轨段 → 无音轨成片。
    # 用探测而不是匹配 ffmpeg 的报错文本：文本随版本/语言变，探测结果是结构化的。
    # 行为变更：Phase C 之前无音轨成片是静默交付的，现在硬失败（近乎无声的片子不该交付）。
    if not probe.probe(file_path).has_audio:
        raise LoudnessError(f"成片没有音轨，无法归一响度：{file_path.name}")
    work_dir.mkdir(parents=True, exist_ok=True)
    staged = work_dir / "loudness_stage.mp4"
    gate = target.true_peak_dbtp + _TP_GATE_MARGIN_DB
    filter_ask = filter_true_peak_ask(target)

    source = parse_gate_reading(_run(measure_gate_args(str(file_path))))
    gain_db = target.integrated_lufs - source.integrated_lufs
    predicted_tp = source.true_peak_dbtp + gain_db
    # 判据必须在**编码之前**把热素材挡掉，不能指望增益路后面那道限幅网兜住。
    # 真机实测（8.1.1-essentials，`intro_narration_275746`：I=-9.80 / TP=+3.20 / crest 13.0 dB，
    # 把判据改成恒真逼它走增益路）：gain=-4.20 dB + 天花板 -2.5 dBTP 的限幅网，编出来
    # **TP=+0.10 dBTP**——比网高 2.6 dB，而且在 0 dBTP 之上（听得见的削顶）。
    # 即**alimiter 接不住已经削平的素材**，与混音限幅器那边同一条账：平顶波形的 AAC 过冲
    # 远大于干净信号（实测数字见 plan 的 Task 8「增补」）。
    # 代价还不止质量：复核不过 → 退回 loudnorm 路 → 整片白编一遍（209.7 s 的片子），
    # 结局与一开始就走 loudnorm 逐字相同（同样 `真峰值超标：-0.3 dBTP` 硬失败）。
    mode = "gain" if predicted_tp <= filter_ask else "loudnorm"
    # 走了哪条路必须留痕（与下面真峰重试那行同一个规矩）：出问题时第一件事就是问
    # "这片子是纯增益归一的还是被压过动态的"，没有这行就只能重跑一遍才知道。
    _LOGGER.info(
        "响度归一走 %s 路：%s 实测 I=%.2f LUFS / TP=%.2f dBTP（门禁量法 ebur128）→ "
        "目标 I=%.2f LUFS，gain=%+.2f dB，预计 TP=%.2f（滤镜侧要 ≤%.2f，门限 ≤%.2f）",
        mode,
        file_path.name,
        source.integrated_lufs,
        source.true_peak_dbtp,
        target.integrated_lufs,
        gain_db,
        predicted_tp,
        filter_ask,
        gate,
    )

    if mode == "gain":
        _run(gain_normalize_args(str(file_path), str(staged), target, gain_db))
        checked = _measure_staged(staged)
        drift = abs(checked.integrated_lufs - target.integrated_lufs)
        if drift <= _TOLERANCE_LU and checked.true_peak_dbtp <= gate:
            os.replace(staged, file_path)
            return checked
        # 退路为什么必须有（真机实测，`ultra_short_hook_2c9b87`）：按最后一块读数
        # I=-8.9/TP=+1.9 算，gain=-5.10 dB 之后真峰"应该"落在 -3.2，实际编出来是
        # **-1.4 dBTP**，差了 1.8 dB——比 `_TP_ENCODE_HEADROOM_DB`(1.0) 与门限余量(0.5)
        # 加起来还多。原因是那两块读数各只覆盖片子的一段（音轨中途换声道布局，见
        # `parse_gate_reading`），而重编之后音轨变均匀、复核量的是整片。
        # 同一条毛病本轮在 `ultra_short_hook_67ee9c`（15.32 s，同样 2 块 Summary）上复现并量全。
        # 连跑两次，决策读数分别是 I=-9.00 与 I=-8.50（最后一块自己就不复现，见
        # `parse_gate_reading`），gain=-5.00 / -5.50 dB，产物分别是
        # **I=-12.80（偏 1.20 LU）/ TP=-1.10** 与 **I=-13.80（偏 0.20 LU）/ TP=-2.10**——
        # 两次都在门限之内（容差 2.0 LU、门限 -1.0 dBTP），gain 路自己过门。
        # 同一部片子走改动前那条 loudnorm-only 算法**两次都失败，而且失败原因还不一样**：
        # 第一次 `真峰值超标 -0.4 dBTP（重试后仍超）`，第二次 `偏离目标 2.0 LU（自报 -16.0）`。
        # 第一次那轮的预测误差量到了底：预计 TP=-3.70，产物实测 -1.10，**差 2.60 dB**。
        # 1.20 LU 已经吃掉容差的六成，而决策读数连跑 5 次极差 1.2 LU
        # ——**预测失准是常态而不是意外**，所以退路必须在。
        # 预测失准就直接硬失败的话，本来就过门的模式会凭空多一种死法。只退一次：
        # 打不到的目标必须响，不许循环到成功为止。
        _LOGGER.warning(
            "gain 路复核没过（integrated=%.2f 偏离 %.1f LU / tp=%.2f 对门限 %.2f），"
            "退回 loudnorm 路：%s",
            checked.integrated_lufs,
            drift,
            checked.true_peak_dbtp,
            gate,
            file_path.name,
        )

    measurement = parse_measurements(_run(measure_args(str(file_path), target)))
    headroom_db = _TP_ENCODE_HEADROOM_DB
    retried = False
    while True:
        _run(
            normalize_args(
                str(file_path), str(staged), target, measurement, headroom_db=headroom_db
            )
        )
        checked = _measure_staged(staged)
        drift = abs(checked.integrated_lufs - target.integrated_lufs)
        if drift > _TOLERANCE_LU:
            # 不重试：偏离目标是电平问题，多要真峰余量只会让它更偏（见 _TP_RETRY_HEADROOM_DB）。
            raise LoudnessError(
                f"响度归一后仍偏离目标 {drift:.1f} LU"
                f"（实测 {checked.integrated_lufs:.1f} / 目标 {target.integrated_lufs:.1f}）"
            )
        if checked.true_peak_dbtp > gate:
            if retried:
                raise LoudnessError(
                    f"真峰值超标：{checked.true_peak_dbtp:.1f} dBTP"
                    f"（滤镜余量 {_TP_RETRY_HEADROOM_DB} dB 重试后仍超门限 {gate:.1f}）"
                )
            retried = True
            headroom_db = _TP_RETRY_HEADROOM_DB
            _LOGGER.warning(
                "真峰值复核超标（%.2f dBTP > 门限 %.2f），loudnorm 路滤镜余量 %.1f→%.1f dB "
                "重试一次：%s",
                checked.true_peak_dbtp,
                gate,
                _TP_ENCODE_HEADROOM_DB,
                _TP_RETRY_HEADROOM_DB,
                file_path.name,
            )
            continue
        if retried:
            # 留痕：队列页/门禁据此区分"一次过门"与"重试过门"（没有这行 info 就是一次过）。
            _LOGGER.info(
                "响度归一重试过门（loudnorm 路，滤镜余量 %.1f dB）：%s "
                "integrated=%.2f LUFS / tp=%.2f dBTP",
                headroom_db,
                file_path.name,
                checked.integrated_lufs,
                checked.true_peak_dbtp,
            )
        os.replace(staged, file_path)
        return checked
