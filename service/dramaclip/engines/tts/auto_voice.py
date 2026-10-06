"""从剧集自动提取参考音色：主角台词最清晰的一段 → 抠音频 → 人声分离。

解决的摩擦：克隆引擎需要 3~10 秒参考音色，让用户自己去剧集里找一段干净的
很麻烦——而分析数据里连「谁在什么时候说了什么」都有。选**台词量最大的
主角**最清晰的 4~10 秒连续段，抽出人声、跑 MDX-Net 分离去 BGM。

挑选规则：
- 主角 = 台词字数最多的说话人（声纹聚类标签，同标签即同一人）；
- 连续段 4~10s 直接用，越接近 7s 越好（短了音色信息不足，长了混入他人插话）；
- 主角没有合适连续段时，取其最长段居中截 8s；
- 全都找不到（无转写/无说话人/段全过短）→ ValueError，调用方如实转达。
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from dramaclip.engines.tts import reference_clean, vocal_separation
from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg
from dramaclip.infra.storage.repos import analysis as analysis_repo

_MIN_S, _MAX_S, _TARGET_S = 4.0, 10.0, 8.0
_EXTRACT_AR = 24000

# 一次提取 = ffmpeg 抽段 + MDX 分离，全程秒级文件名落盘。并发出片批里多条
# 任务同时走到这里会互踩（同秒同名 raw、先洗完先删、MDX 模型并发加载），
# 所以整条提取管线串行；可重入——调用方可在锁内先查再调 extract_auto_voice。
_EXTRACT_LOCK = threading.RLock()


def extract_lock() -> threading.RLock:
    """提取串行锁：调用方要「锁内查最新音色、没有才提取」时用它包住整段。"""
    return _EXTRACT_LOCK


def _segments_of(analysis_row: dict[str, Any]) -> list[dict[str, Any]]:
    raw = analysis_row.get("asr_segments", "[]")
    try:
        segments = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [s for s in segments if isinstance(s, dict) and s.get("text")]


def _lead_speaker(segments: list[dict[str, Any]]) -> str | None:
    """台词字数最多的说话人 = 主角；无说话人标签（旧分析）返回 None。"""
    totals: dict[str, int] = {}
    for seg in segments:
        speaker = seg.get("speaker")
        if not speaker:
            continue
        totals[str(speaker)] = totals.get(str(speaker), 0) + len(str(seg.get("text") or ""))
    return max(totals, key=lambda s: totals[s]) if totals else None


def _pick_span(segments: list[dict[str, Any]], speaker: str) -> tuple[float, float] | None:
    """主角的可用连续段：4~10s 直接取（越接近 7s 越好）；过长段居中截 _TARGET_S。"""
    own = [s for s in segments if s.get("speaker") == speaker]
    inline = [
        (float(s["start"]), float(s["end"]))
        for s in own
        if _MAX_S >= float(s["end"]) - float(s["start"]) >= _MIN_S
    ]
    if inline:
        return min(inline, key=lambda span: abs(span[1] - span[0] - 7.0))
    longs = [
        (float(s["start"]), float(s["end"]))
        for s in own
        if float(s["end"]) - float(s["start"]) > _MAX_S
    ]
    if longs:
        start, end = max(longs, key=lambda span: span[1] - span[0])
        mid = (start + end) / 2
        return (mid - _TARGET_S / 2, mid + _TARGET_S / 2)
    return None


def pick_best_span(
    conn: Any, episodes: list[dict[str, Any]]
) -> tuple[dict[str, Any], float, float, str] | None:
    """在给定集行里选最优：(集行, start, end, 主角)。时长越接近 7s 越优。"""
    rows = episodes
    best: tuple[float, dict[str, Any], float, float, str] | None = None
    for row in rows:
        record = analysis_repo.get(conn, str(row["id"]))
        if record is None:
            continue
        segments = _segments_of(record)
        speaker = _lead_speaker(segments)
        if speaker is None:
            continue
        span = _pick_span(segments, speaker)
        if span is None:
            continue
        score = abs(span[1] - span[0] - 7.0)
        if best is None or score < best[0]:
            best = (score, row, span[0], span[1], speaker)
    if best is None:
        return None
    _, row, start, end, speaker = best
    return (row, start, end, speaker)


def extract_auto_voice(conn: Any, data_dir: Path, episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """主入口：选段 → ffmpeg 抽音频 → 人声分离 → 落盘。返回给前端展示/直接采用。"""
    with _EXTRACT_LOCK:
        return _extract_locked(conn, data_dir, episodes)


def _extract_locked(conn: Any, data_dir: Path, episodes: list[dict[str, Any]]) -> dict[str, Any]:
    picked = pick_best_span(conn, episodes)
    if picked is None:
        raise ValueError(
            "剧集中没有可用的参考段：需要先完成剧集分析（带说话人），"
            "且主角有 4 秒以上的连续台词"
        )
    row, start, end, speaker = picked
    source = Path(str(row["source_path"]))
    if not source.is_file():
        raise ValueError(f"源文件不在盘上：{source}")

    voices_dir = data_dir / "voices"
    voices_dir.mkdir(parents=True, exist_ok=True)
    stamp = f"{time.strftime('%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
    raw_path = voices_dir / f"auto-raw-{stamp}.wav"
    subprocess.run(
        [
            resolve_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-i", str(source),
            "-vn", "-ac", "1", "-ar", str(_EXTRACT_AR), str(raw_path),
        ],
        capture_output=True, timeout=120, check=True,
    )

    models_dir = data_dir / "models"
    try:
        final = vocal_separation.clean_reference(models_dir, raw_path)
    except Exception:  # noqa: BLE001 - MDX 不可用回退滤镜清洗，仍比不洗强
        final = reference_clean.clean_reference(raw_path)
    raw_path.unlink(missing_ok=True)

    final_name = voices_dir / f"auto-ref-{stamp}.wav"
    final.rename(final_name)
    return {
        "path": str(final_name),
        "speaker": speaker,
        "start": round(start, 2),
        "end": round(end, 2),
        "seconds": round(end - start, 1),
    }
