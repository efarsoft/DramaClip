"""分析记录 JSON 字段 → 结构化输入的宽容解析族。

自 api/narration_plans.py 拆出（拆分专项）：全部是**纯函数**——不触 DB、
不依赖 AppContext，输入是落库的 JSON 字符串/字段，输出是构造好的
casting 原料（AudioFeatures / 静音区间 / 拍点 / 窗口表 / 切点表 / 冲突 /
高光）。坏数据一律降级为空表、不 raise（编排层不为解析失败付「这条方案
出不了片」的代价），与 narration_plans 的既有纪律一致。

两个消费方：api/narration_plans._collect_episode_inputs / _casting_for，
以及 api/narration（scene_cuts_of 单点）。
"""

from __future__ import annotations

import json
from typing import Any

from dramaclip.engines.analysis.models import AudioFeatures
from dramaclip.engines.semantic.models import ConflictScore, HighlightSegment


def audio_of(raw: Any) -> Any:
    """audio_features JSON → AudioFeatures（坏形归空，与 beats 同款宽容）。"""
    try:
        return AudioFeatures.model_validate(json.loads(raw) if raw else {})
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def silences_of(audio: Any) -> tuple[tuple[float, float], ...]:
    """speech_zones 的补集=声学静音区间：句界吸附的精修依据（T1 质批）。

    解析失败/字段缺失返回空元组——静音精修是增强不是义务，不为它重分析。
    """
    zones = getattr(audio, "speech_zones", None) or []
    spans = [
        (float(zone.start), float(zone.end))
        for zone in zones
        if float(zone.end) > float(zone.start)
    ]
    if not spans:
        return ()
    silences: list[tuple[float, float]] = []
    if spans[0][0] > 0.0:
        silences.append((0.0, spans[0][0]))
    for (_, prev_end), (next_start, _) in zip(spans, spans[1:], strict=False):
        if next_start - prev_end > 1e-6:
            silences.append((prev_end, next_start))
    return tuple(silences)


def parse_beats(raw: str | None) -> tuple[float, ...]:
    """从落库的 audio_features JSON 取拍点表（B9）。

    缺失/坏 JSON 一律返回空元组、**不 raise**：节拍吸附是编排层的意图增强
    （见 engines/narration/beat_align），装配层不为它付「这条方案出不了片」的
    代价；旧库记录没有 beats 字段时同样落到这里，降级为不吸附。
    """
    if not raw:
        return ()
    try:
        return tuple(AudioFeatures.model_validate(json.loads(raw)).beats)
    except (json.JSONDecodeError, ValueError):
        return ()


def scored_windows_of(raw: Any) -> list[dict[str, Any]]:
    """[{"start","end","score","reason"}] 形状窗口的宽容解析；坏数据逐条跳过。"""
    try:
        items = json.loads(str(raw)) if raw else []
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(items, list):
        return []
    windows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            windows.append(
                {
                    "start": float(item["start"]),
                    "end": float(item["end"]),
                    "score": float(item.get("score") or 0.0),
                    "reason": str(item.get("reason") or "").strip(),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return windows


def visual_frames_of(raw: Any) -> list[dict[str, Any]]:
    """visual_track JSON → 紧凑画面轨条目；缺失/坏数据 → 空表（分档，不报错）。

    保留判据是任一描述维非空（scene/shot/people/action）——此前只认 scene，
    特写类帧常无场景词（scene 空、shot=特写），整条被丢弃的同时把
    scene_visual_score 的 watch_score 平均也一起带漏（三消费面共享此漏点）。
    """
    try:
        track = json.loads(str(raw)) if raw else {}
    except (json.JSONDecodeError, TypeError):
        return []
    frames = track.get("frames") if isinstance(track, dict) else None
    if not isinstance(frames, list):
        return []

    def _describable(frame: dict[str, Any]) -> bool:
        return any(
            str(frame.get(key, "")).strip()
            for key in ("scene", "shot", "people", "action")
        )

    return [frame for frame in frames if isinstance(frame, dict) and _describable(frame)]


def parse_conflicts(raw: str | None) -> list[ConflictScore]:
    return [ConflictScore.model_validate(item) for item in json.loads(raw or "[]")]


def scene_cuts_of(raw: Any) -> list[float]:
    """scene_data 落库是 JSON 字符串：解析出镜头切点表，坏形返回空表不 raise。"""
    try:
        scenes = json.loads(raw) if raw else []
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(scenes, list):
        return []
    cuts: list[float] = []
    for scene in scenes:
        try:
            cut = round(float(scene["start"]), 2)
        except (KeyError, TypeError, ValueError):
            continue
        if cut > 0:
            cuts.append(cut)
    return cuts


def parse_highlights(raw: str | None) -> list[HighlightSegment]:
    return [HighlightSegment.model_validate(item) for item in json.loads(raw or "[]")]
