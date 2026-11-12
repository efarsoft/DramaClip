"""硬件编码器探测：平台候选序 + 同形状质量参数真试编 + 会话级缓存。

自 encoder.py 拆出（拆分专项）：硬编探测是导出编码的独立增强层——
候选序按平台，每个候选用 0.1s 黑帧**真试编**验证（带与正式合成同形状
的质量参数），通过后会话级缓存选中结果。调用方 encoder.export_plan /
_run_export。`pick_hw_encoder` 内部延迟导入 `_run_cut`（encoder.py）
避免循环依赖。
"""

from __future__ import annotations

import logging
import sys
import threading

_LOGGER = logging.getLogger(__name__)

# 硬编候选序按平台：Windows 三厂商 NVENC→AMF→QSV，Linux 只有 NVENC/QSV（AMF 的
# Linux 支持面未实测，不进候选）。编码器「列表里有」≠「真编能过」（驱动残缺/GPU
# 会话数满），所以每个候选都要做 0.1s 黑帧**真试编**——且必须带与正式合成
# **同形状**的质量参数（`_video_codec_params`），只 `-f null` 探不出「参数不识别」
# 这类实编挂。
_HW_CANDIDATES_BY_PLATFORM: dict[str, tuple[str, ...]] = {
    # win32 三厂商：N 卡第一次命中；AMD 主机 nvenc 黑帧失败后第二次命中 AMF；
    # Intel 核显最后兜底。全失败才 libx264。
    "win32": ("h264_nvenc", "h264_amf", "h264_qsv"),
    "darwin": ("h264_videotoolbox",),
}
# 输出色彩统一打 BT.709 标签：短剧源（网络片源）几乎全为 BT.709，无标签流的
# 播放器/平台各自猜矩阵（BT.601 vs 709）是跨平台偏色投诉的来源。重编码段与
# 重编码 concat 都注入；流复制分支保留源标签不动。
_COLOR_ARGS = [
    "-colorspace", "bt709",
    "-color_primaries", "bt709",
    "-color_trc", "bt709",
]

_HW_CANDIDATES_LINUX: tuple[str, ...] = ("h264_nvenc", "h264_qsv")

# 驱动挂起兜底：探测真编不许拖住导出超过 15s（正式段编码仍走 _run_cut 默认 600s）。
_HW_PROBE_TIMEOUT_S = 15.0


def _hw_candidates(platform: str | None = None) -> list[str]:
    """当前平台的硬编候选序（win32/darwin 显式表，其余平台按 linux 序）。"""
    key = sys.platform if platform is None else platform
    if key in _HW_CANDIDATES_BY_PLATFORM:
        return list(_HW_CANDIDATES_BY_PLATFORM[key])
    return list(_HW_CANDIDATES_LINUX)


def _video_codec_params(video_codec: str) -> list[str]:
    """各编码器的质量参数——正式合成与探测真试编读**同一处**构造（不许各写一份）。"""
    if video_codec == "h264_nvenc":
        return ["-preset", "p4", "-tune", "hq", "-rc", "vbr", "-cq", "22"]
    if video_codec == "h264_amf":
        # cqp 22 对齐 NVENC 的 vbr/cq 22 与 QSV 的 global_quality 22；usage=transcoding
        # 对文件导出而非低延迟场景。参数只在这一处定义，探针与正式段共用。
        return [
            "-usage", "transcoding",
            "-quality", "quality",
            "-rc", "cqp",
            "-qp_i", "22", "-qp_p", "22", "-qp_b", "24",
        ]
    if video_codec == "h264_qsv":
        # QSV 用全局质量（ICQ）对齐 NVENC 的 VBR+CQ 语义；preset 名与 x264 系不同。
        return ["-preset", "medium", "-global_quality", "22"]
    if video_codec == "h264_videotoolbox":
        return ["-q:v", "55"]
    # medium：交付场景同 CRF 画质明显优于 veryfast（编码时间约两倍，段级
    # 并行下可接受）；探针真试编与正式段读同一处，签名天然一致。
    return ["-preset", "medium", "-crf", "20"]


def _hw_probe_args(video_codec: str) -> list[str]:
    """0.1s 黑帧真试编命令：与正式段编码同形状的质量参数，输出到 null。"""
    return [
        "-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
        "-c:v", video_codec, *_video_codec_params(video_codec),
        # 色彩参数与正式段同形状（探针验证的是同一输出形状）
        *_COLOR_ARGS,
        "-f", "null", "-",
    ]


_HW_LOCK = threading.Lock()
# 缓存「选中的编码器名」（None=全失败也缓存）：会话级结果，防换卡/驱动更新后陈旧
# 的代价由进程生命周期界定；旧 _NVENC_CACHE(bool) 形状被 pick_hw_encoder 取代。
_HW_ENCODER_CACHE: str | None = None


def pick_hw_encoder() -> str | None:
    """返回第一个真试编通过的硬编编码器名；全失败/探测自身异常返回 None。

    探测自身的任何异常（驱动崩溃、OSError）都吞掉按不可用处理——best-effort 增强
    绝不反过来把本来能软编成功的导出挡死。
    """
    global _HW_ENCODER_CACHE  # noqa: PLW0603
    with _HW_LOCK:
        if _HW_ENCODER_CACHE is None:
            chosen: str | None = None
            for candidate in _hw_candidates():
                try:
                    from dramaclip.engines.exporter.encoder import _run_cut  # noqa: PLC0415
                    _run_cut(_hw_probe_args(candidate), timeout_s=_HW_PROBE_TIMEOUT_S)
                except Exception:  # noqa: BLE001 - 驱动/会话异常一律按该候选不可用
                    continue
                chosen = candidate
                break
            # 用哨兵区分「还没探过」与「探过、全失败」：全失败缓存为 ""，
            # 避免每次导出都重试真编（黑帧 0.1s×候选数，机器慢时是秒级）。
            _HW_ENCODER_CACHE = chosen if chosen is not None else ""
            if chosen is None:
                _LOGGER.info("硬编探测：所有候选不可用，回退 libx264")
            else:
                _LOGGER.info("硬编探测：选用 %s", chosen)
        return _HW_ENCODER_CACHE or None


def nvenc_available() -> bool:
    """旧签名兼容（api/export.py 无参调用）：严格语义 = pick_hw_encoder() 选中 NVENC。

    不放宽成「任何硬编可用」：调用方拿到 True 后写死 h264_nvenc，若这里在 mac 上因
    videotoolbox 返回 True 就会用 NVENC 真编挂掉。新调用方直接用 pick_hw_encoder()。
    """
    return pick_hw_encoder() == "h264_nvenc"
