"""硬字幕 OCR 通道：短剧自带人工校对字幕，是台词文本的视觉金标准。

抽取流程：定位字幕带（每集前 4 个探针帧全帧检测，取台词文本密集高度带）→
按 1fps 抽帧裁剪字幕带 → 逐帧识别 → 相邻同文本帧合并为字幕条。
持续占据固定位置的横幅（免责声明等）在定位阶段排除，不进结果。

依赖属 ml extras：rapidocr 懒加载，未安装时调用方降级为纯 ASR 路径。
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from dramaclip.engines.analysis.models import OcrSegment
from dramaclip.engines.analysis.transcriber import simplify
from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg

_LOGGER = logging.getLogger(__name__)

_PROBE_COUNT = 4          # 字幕带定位的探针帧数
_SAMPLE_FPS = 1.0         # 抽帧率：短剧镜头 1.5~3s，字幕驻留普遍 ≥1s
_ROI_WIDTH = 800          # 裁剪后缩放宽（识别耗时与像素量成正比）
_BAND_EXPAND = 0.04       # 字幕带上下各扩 4% 画面高，容納描边/阴影
_HEAD_PAD_S = 0.5         # 字幕条起点向前补（采样间隔一半）
_TAIL_PAD_S = 1.0         # 字幕条结尾向后补（采样间隔 + 消失延迟）
_MERGE_RATIO = 0.85       # 相邻帧文本相似度阈值（OCR 抖动容差）

# OCR 单帧结果：文本 + 归一化纵向位置（top, bottom）
FrameResult = list[tuple[str, float, float, float]]
OcrCallable = Callable[[str], FrameResult]


@dataclass(frozen=True)
class _Band:
    """字幕带（画面高度归一化区间）。"""

    top: float
    bottom: float


def extract_subtitles(
    video_path: Path,
    work_dir: Path,
    *,
    duration_s: float,
    ocr: OcrCallable | None = None,
) -> list[OcrSegment]:
    """抽取全集硬字幕条。ocr 可注入（测试）；缺省懒加载 RapidOCR。"""
    work_dir.mkdir(parents=True, exist_ok=True)
    if ocr is None:
        ocr = _rapidocr()
    probes = _probe_frames(video_path, work_dir, duration_s, ocr)
    band = _pick_band([boxes for _t, boxes in probes])
    if band is None:
        _LOGGER.info("未定位到字幕带，跳过 OCR 通道：%s", video_path.name)
        return []
    frames = _sample_frames(video_path, work_dir, band)
    results: list[tuple[float, FrameResult]] = []
    for index, frame in enumerate(frames):
        boxes = [(t, top, bottom, c) for t, top, bottom, c in ocr(str(frame))]
        t0 = index / _SAMPLE_FPS
        results.append((t0, boxes))
        frame.unlink(missing_ok=True)
    return _merge_runs(results)


def _probe_frames(
    video_path: Path,
    work_dir: Path,
    duration_s: float,
    ocr: OcrCallable,
) -> list[tuple[float, FrameResult]]:
    """全帧检测探针帧：返回 (时刻, 全帧结果)。"""
    out: list[tuple[float, FrameResult]] = []
    for index in range(_PROBE_COUNT):
        second = duration_s * (index + 1) / (_PROBE_COUNT + 1)
        frame = _extract_frame(video_path, work_dir, second)
        if frame is None:
            continue
        boxes = [(t, top, bottom, c) for t, top, bottom, c in ocr(str(frame))]
        out.append((second, boxes))
        frame.unlink(missing_ok=True)
    return out


def _pick_band(probes: list[FrameResult]) -> _Band | None:
    """定位台词字幕带：探针帧中出现最多的纵向位置簇，排除常驻横幅。

    常驻横幅（免责声明等）特征 = 文本在多数探针帧中重复出现于同一位置。
    """
    if not probes:
        return None
    by_text: dict[str, list[tuple[float, float]]] = {}
    for boxes in probes:
        for text, top, bottom, _c in boxes:
            by_text.setdefault(text, []).append((round(top, 2), round(bottom, 2)))
    persistent: list[tuple[float, float]] = []
    for _text, spots in by_text.items():
        if len(spots) >= max(2, len(probes) - 1):
            persistent.extend(spots)
    candidates = [
        (top, bottom)
        for boxes in probes
        for text, top, bottom, _c in boxes
        if (round(top, 2), round(bottom, 2)) not in persistent
    ]
    if not candidates:
        return None
    tops = sorted(top for top, _b in candidates)
    anchor = tops[len(tops) // 2]  # 中位数位置为字幕带锚点
    same_band = [
        (top, bottom) for top, bottom in candidates if abs(top - anchor) <= _BAND_EXPAND * 2
    ]
    top = min(top for top, _b in same_band)
    bottom = max(bottom for _t, bottom in same_band)
    return _Band(max(0.0, top - _BAND_EXPAND), min(1.0, bottom + _BAND_EXPAND))


def _extract_frame(video_path: Path, work_dir: Path, at: float) -> Path | None:
    """抽单张全帧（字幕带定位用）。"""
    out_path = work_dir / f"_ocr_probe_{at:.2f}.jpg"
    cmd = [
        resolve_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{at:.3f}", "-i", str(video_path),
        "-frames:v", "1", str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=120)  # noqa: S603
    if result.returncode != 0 or not out_path.is_file():
        return None
    return out_path


def _sample_frames(video_path: Path, work_dir: Path, band: _Band) -> list[Path]:
    """按 1fps 抽帧并裁剪字幕带（时间戳 = 帧序号 / 采样率）。"""
    out_dir = work_dir / "ocr_frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("f*.jpg"):
        old.unlink(missing_ok=True)
    crop = (
        f"crop=iw:ih*{(band.bottom - band.top) * 100:.0f}/100:0:ih*{band.top * 100:.0f}/100,"
        f"scale={_ROI_WIDTH}:-1"
    )
    cmd = [
        resolve_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video_path),
        "-vf", f"fps={_SAMPLE_FPS},{crop}",
        str(out_dir / "f%04d.jpg"),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=600)  # noqa: S603
    return sorted(out_dir.glob("f*.jpg"))


def _merge_runs(results: list[tuple[float, FrameResult]]) -> list[OcrSegment]:
    """相邻帧同文本合并为字幕条：时间取首末帧（前后补采样间隔），文本取最长。

    帧内多行（两行字幕）按纵向位置序拼接为一条；坐标已在裁剪带内，无需再过滤。
    """
    frame_texts: list[tuple[float, str, float]] = []
    for t0, boxes in results:
        if not boxes:
            frame_texts.append((t0, "", 0.0))
            continue
        ordered = sorted(boxes, key=lambda box: box[1])
        text = simplify("".join(box[0] for box in ordered))
        conf = sum(box[3] for box in ordered) / len(ordered)
        frame_texts.append((t0, text, float(conf)))

    segments: list[OcrSegment] = []
    run_text: str | None = None
    run_start = run_end = 0.0
    run_confs: list[float] = []

    def flush() -> None:
        if run_text is None:
            return
        segments.append(
            OcrSegment(
                start=round(max(0.0, run_start - _HEAD_PAD_S), 3),
                end=round(run_end + _TAIL_PAD_S, 3),
                text=run_text,
                conf=round(sum(run_confs) / len(run_confs), 3) if run_confs else 1.0,
            )
        )

    for t0, text, conf in frame_texts:
        if not text:
            flush()
            run_text = None
            run_confs = []
            continue
        if run_text is not None and _similar(text, run_text):
            run_end = t0
            run_confs.append(conf)
            if len(text) > len(run_text):
                run_text = text
        else:
            flush()
            run_text, run_start, run_end = text, t0, t0
            run_confs = [conf]
    flush()
    return segments


def _similar(a: str, b: str) -> bool:
    return a == b or SequenceMatcher(None, a, b).ratio() >= _MERGE_RATIO


def _rapidocr() -> OcrCallable:
    """懒加载 RapidOCR（ml extras），输出归一化为 FrameResult。"""
    from rapidocr_onnxruntime import RapidOCR  # ml extras 懒加载

    engine = RapidOCR()

    def call(image_path: str) -> FrameResult:
        raw, _elapse = engine(image_path)
        if not raw:
            return []
        height = _image_height(image_path)
        return [
            (str(item[1]), min(p[1] for p in item[0]) / height,
             max(p[1] for p in item[0]) / height, float(item[2]))
            for item in raw
        ]

    return call


def _image_height(image_path: str) -> float:
    from PIL import Image  # rapidocr 已依赖 pillow

    with Image.open(image_path) as image:
        return float(image.height)
