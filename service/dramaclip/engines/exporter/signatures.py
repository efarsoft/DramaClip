"""段级签名与缓存：内容寻址 + 断点续跑 + 字幕复用校验。

自 encoder.py 拆出（拆分专项）：段签名（sidecar .sig）记录输入标识与产物记录，
供断点续跑判定复用。签名版本号在此定义（encoder 导入），签名读写是原子操作
（tmp+replace），崩溃只丢 sig 不丢产物。字幕复用校验用签名里记录的上次窗口
重新生成 ass、hash 比对——证明预设/拆行/emotion 没变才允许复用。
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dramaclip.engines.analysis.models import SpeechZone
from dramaclip.engines.narration.models import TimelineSegment

_SIG_VERSION = 1


def _sig_path_for(seg_path: Path) -> Path:
    return seg_path.with_suffix(".sig")


def _sha256_file(path: str | Path) -> str | None:
    """文件内容 sha256；读不到返回 None（调用方按不可复用处理）。"""
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _file_identity(path: str | Path) -> dict[str, object]:
    """源文件身份：path+size+mtime_ns。stat 失败给 -1（必与任何真实签名不等）。"""
    try:
        stat = Path(path).stat()
    except OSError:
        return {"path": str(path), "size": -1, "mtime_ns": -1}
    return {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _zones_fingerprint(zones: list[SpeechZone]) -> str:
    """台词保护区内容哈希：手工 .srt 或库内 ASR 变了，切点语义就变了，不许复用。"""
    payload = json.dumps([[zone.start, zone.end] for zone in zones])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_sig(seg_path: Path) -> dict[str, Any] | None:
    """读 sidecar 签名：缺任何一边/损坏/版本或形状不对都返回 None（按不可复用）。

    产物必须非空（与 A5 缓存的 `_usable` 同判据）：0 字节残留不是可复用产物。
    """
    sig_path = _sig_path_for(seg_path)
    if not sig_path.is_file():
        return None
    try:
        if not (seg_path.is_file() and seg_path.stat().st_size > 0):
            return None
        payload = json.loads(sig_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # ValueError 含 JSONDecodeError：损坏按不可复用
        return None
    if not isinstance(payload, dict) or payload.get("version") != _SIG_VERSION:
        return None
    inputs = payload.get("inputs")
    recorded = payload.get("recorded")
    if not isinstance(inputs, dict) or not isinstance(recorded, dict):
        return None
    return {"inputs": inputs, "recorded": recorded}


def _write_sig_atomic(seg_path: Path, payload: dict[str, Any]) -> None:
    """签名原子落盘（tmp+replace，A5 缓存同形状）：崩溃只会丢 sig，不会留半截可误读的。"""
    sig_path = _sig_path_for(seg_path)
    tmp = seg_path.with_name(f"{seg_path.stem}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        os.replace(tmp, sig_path)
    finally:
        tmp.unlink(missing_ok=True)


def _reusable_subtitles(
    index: int,
    segment: TimelineSegment,
    recorded: dict[str, Any],
    subtitle_source: str,
    subtitle_burner: Callable[[int, str, float], str] | None,
    original_subtitle_provider: Callable[[int, float, float], str | None] | None,
) -> bool:
    """复用候选段的字幕校验：用**上次记录的窗口**重新生成 ass，内容 hash 必须与记录一致。

    为什么必须重新生成而不是「旧 ass 文件还在就行」：ass 字节由预设、拆行逻辑、
    emotion 标签共同决定，编码器看不见这些量；重新生成一遍才证明它们没变。
    生成窗口取 sig 里记的上次值而非本次 jitter 切点——否则时间字段必然不同，
    复用永不命中（rng 无种子）。任何异常/hash 不一致→不可复用（重编）。
    """
    if recorded.get("subtitle_source") != subtitle_source:
        return False
    want = recorded.get("ass_sha256")
    produced: str | None = None
    try:
        if subtitle_source == "burner":
            if subtitle_burner is None:
                return False
            produced = subtitle_burner(
                index, str(segment.subtitle_text or ""), float(recorded["duration_s"])
            )
        elif subtitle_source == "provider":
            if original_subtitle_provider is None:
                return False
            produced = original_subtitle_provider(
                index, float(recorded["safe_start"]), float(recorded["safe_end"])
            )
        elif subtitle_source != "none":
            return False
    except Exception:  # noqa: BLE001 - 校验失败按不可复用处理，绝不挡正常编码
        return False
    if produced is None:
        return want is None
    return want is not None and _sha256_file(produced) == want


def _prune_stale_segments(work_dir: Path, segment_count: int) -> None:
    """清掉上次更长的计划留下的 seg/sig 尾段（索引 >= 本次段数）。

    Phase B 已改成按 jobs 清单取段（`_concat_manifest`），尾段进不了成片；这里清它们
    只为不留垃圾占盘、不让 sig 复用判据在下次更长的计划里吃到过期产物。
    只按 seg_NNN 命名清 .mp4/.sig 两种，不碰 api 层的 seg_NNN.ass。
    """
    for pattern in ("seg_*.mp4", "seg_*.sig"):
        for path in work_dir.glob(pattern):
            try:
                index = int(path.stem.rsplit("_", 1)[-1])
            except ValueError:
                continue
            if index >= segment_count:
                path.unlink(missing_ok=True)
