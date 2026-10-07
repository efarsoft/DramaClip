"""硬字幕 OCR 通道：短剧自带人工校对字幕，是台词文本的视觉金标准。
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from dramaclip.engines.analysis.models import OcrSegment
from dramaclip.engines.analysis.transcriber import simplify
from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg

_LOGGER = logging.getLogger(__name__)

_PROBE_COUNT = 10         # 字幕带定位探针帧数：台词有行间空隙，4 探针可能全落空（ep4 实证）
_SAMPLE_FPS = 1.0         # 抽帧率：短剧镜头 1.5~3s，字幕驻留普遍 ≥1s
_ROI_WIDTH = 800          # 裁剪后缩放宽（识别耗时与像素量成正比）
_BAND_EXPAND = 0.04       # 字幕带上下各扩 4% 画面高，容納描边/阴影
_HEAD_PAD_S = 0.5         # 字幕条起点向前补（采样间隔一半）
_TAIL_PAD_S = 1.0         # 字幕条结尾向后补（采样间隔 + 消失延迟）
_OCR_WORKERS = 4        # 帧识别并行度（onnxruntime session 线程安全）
_MERGE_RATIO = 0.85       # 相邻帧文本相似度阈值（OCR 抖动容差）
_MIN_BAR_CHARS = 2        # 字幕条最短字数：单字残条=切镜半帧噪声

# OCR 单帧结果：文本 + 归一化纵向位置（top, bottom）
FrameResult = list[tuple[str, float, float, float]]
OcrCallable = Callable[[str], FrameResult]


@dataclass(frozen=True)
class _Band:
    """字幕带（画面高度归一化区间）。"""

    top: float
    bottom: float


def detect_band(
    video_path: Path,
    work_dir: Path,
    *,
    duration_s: float,
    ocr: OcrCallable | None = None,
) -> tuple[float, float] | None:
    """探测台词字幕带位置（top/bottom 占帧高比例），供导出遮罩定位。"""
    work_dir.mkdir(parents=True, exist_ok=True)
    if ocr is None:
        ocr = _rapidocr()
    probes = _probe_frames(video_path, work_dir, duration_s, ocr)
    band = _pick_band([boxes for _t, boxes in probes])
    if band is None:
        return None
    return (band.top, band.bottom)


def extract_subtitles(
    video_path: Path,
    work_dir: Path,
    *,
    duration_s: float,
    ocr: OcrCallable | None = None,
    band: tuple[float, float] | None = None,
) -> tuple[list[OcrSegment], tuple[float, float] | None, list[tuple[float, float]] | None]:
    """抽取全集硬字幕条，并回传 (segments, band, 行框列表)。

    ocr 可注入（测试）；band 可传入已探测的字幕带（原样回传，行框未知为 None）。
    band/行框是覆盖数据链的起点：调用方落库 episode_analysis.subtitle_band，编码端
    delogo 逐行擦除、烧录字幕带内压位。未探到带时 band/行框均为 None（NULL 语义：
    无硬字幕带/未探测，消费端一律回退现状）。
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    if ocr is None:
        ocr = _rapidocr()
    picked_band: _Band | None = None
    lines: list[_Band] | None = None
    if band is not None:
        picked_band = _Band(top=band[0], bottom=band[1])
    if picked_band is None:
        probes = _probe_frames(video_path, work_dir, duration_s, ocr)
        candidates = _dialogue_candidates([boxes for _t, boxes in probes])
        picked_band = _band_from(candidates)
        lines = _cluster_lines(candidates)
    if picked_band is None:
        _LOGGER.info("未定位到字幕带，跳过 OCR 通道：%s", video_path.name)
        return [], None, None
    frames = _sample_frames(video_path, work_dir, picked_band)

    def _recognize(indexed: tuple[int, Path]) -> tuple[float, FrameResult, Path]:
        index, frame = indexed
        boxes = [(t, top, bottom, c) for t, top, bottom, c in ocr(str(frame))]
        return (index / _SAMPLE_FPS, boxes, frame)

    # 帧级并行：onnxruntime 的 session.run 线程安全，4 路在 CPU 档约 3 倍提速
    results: list[tuple[float, FrameResult]] = []
    with ThreadPoolExecutor(max_workers=_OCR_WORKERS) as pool:
        for t0, boxes, frame in pool.map(_recognize, enumerate(frames)):
            results.append((t0, boxes))
            frame.unlink(missing_ok=True)
    line_rects = (
        [(b.top, b.bottom) for b in lines] if lines is not None else None
    )
    return (
        _merge_runs(results),
        (picked_band.top, picked_band.bottom),
        line_rects,
    )


def _probe_frames(
    video_path: Path,
    work_dir: Path,
    duration_s: float,
    ocr: OcrCallable,
) -> list[tuple[float, FrameResult]]:
    """全帧检测探针帧：返回 (时刻, 全帧结果)。"""
    out: list[tuple[float, FrameResult]] = []
    for index in range(_PROBE_COUNT):
        second = duration_s * (index + 0.5) / _PROBE_COUNT  # 错位取样，避开片头片尾
        frame = _extract_frame(video_path, work_dir, second)
        if frame is None:
            continue
        boxes = [(t, top, bottom, c) for t, top, bottom, c in ocr(str(frame))]
        out.append((second, boxes))
        frame.unlink(missing_ok=True)
    return out


def _dialogue_candidates(probes: list[FrameResult]) -> list[tuple[float, float]]:
    """探针帧里的台词字幕行位置（排除常驻横幅：几乎每帧都在同一位置的框）。"""
    by_text: dict[str, list[tuple[float, float]]] = {}
    for boxes in probes:
        for text, top, bottom, _c in boxes:
            by_text.setdefault(text, []).append((round(top, 2), round(bottom, 2)))
    persistent: list[tuple[float, float]] = []
    for _text, spots in by_text.items():
        if len(spots) >= max(2, len(probes) - 1):
            persistent.extend(spots)
    return [
        (top, bottom)
        for boxes in probes
        for text, top, bottom, _c in boxes
        if (round(top, 2), round(bottom, 2)) not in persistent
    ]


def _band_from(candidates: list[tuple[float, float]]) -> _Band | None:
    """台词行位置 → 单一包络带（中位锚点聚类，供采样裁剪与 ASS 压位）。"""
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


def _pick_band(probes: list[FrameResult]) -> _Band | None:
    """定位台词字幕带：探针帧中出现最多的纵向位置簇，排除常驻横幅。
    """
    return _band_from(_dialogue_candidates(probes))


def _cluster_lines(candidates: list[tuple[float, float]]) -> list[_Band]:
    """台词行位置 → 逐行框（top 间距超阈值即分行），供 delogo 逐行擦除。

    行级矩形比整带紧：不擦行间空隙与带边缘的画面，涂抹痕迹更小
    （2026-10-07 业主追加：只对检测到的文字行做擦除）。
    """
    if not candidates:
        return []
    tops = sorted(top for top, _b in candidates)
    anchors = [tops[0]]
    for top in tops[1:]:
        if top - anchors[-1] > _BAND_EXPAND * 2:
            anchors.append(top)
    lines: list[_Band] = []
    for anchor in anchors:
        same = [(t, b) for t, b in candidates if abs(t - anchor) <= _BAND_EXPAND * 2]
        if not same:
            continue
        top = min(t for t, _b in same)
        bottom = max(b for _t, b in same)
        lines.append(_Band(max(0.0, top - _BAND_EXPAND), min(1.0, bottom + _BAND_EXPAND)))
    return lines


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
        # 单字残条 = 快速切镜采到半帧字幕，只会污染融合对齐，整条丢弃
        if run_text is None or len(run_text.strip()) < _MIN_BAR_CHARS:
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
