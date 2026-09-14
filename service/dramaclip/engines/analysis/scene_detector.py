"""场景切割：PySceneDetect（懒加载）+ 场景规整洁函数。
"""

from __future__ import annotations

from pathlib import Path

from dramaclip.engines.analysis.models import SceneInfo

_DEFAULT_THRESHOLD = 30.0


def detect_scenes(video_path: Path, *, threshold: float = _DEFAULT_THRESHOLD) -> list[SceneInfo]:
    """物理镜头边界检测（依赖 scenedetect，属 ml extras 懒加载）。"""
    from scenedetect import ContentDetector, detect  # ml extras 懒加载

    scene_list = detect(str(video_path), ContentDetector(threshold=threshold))
    return [
        SceneInfo(start=start.get_seconds(), end=end.get_seconds())
        for start, end in scene_list
    ]


def merge_scenes(
    scenes: list[SceneInfo],
    *,
    min_duration_s: float = 2.0,
    max_duration_s: float = 8.0,
) -> list[SceneInfo]:
    """规整场景：当前段过短且与前邻相邻 → 并入前邻；首/尾段过短 → 吸收相邻段；超长均分。"""
    merged: list[SceneInfo] = []
    for scene in scenes:
        previous = merged[-1] if merged else None
        adjacent = previous is not None and scene.start - previous.end < 0.05
        current_short = scene.end - scene.start < min_duration_s
        if adjacent and current_short and previous is not None:
            merged[-1] = SceneInfo(start=previous.start, end=scene.end)
        else:
            merged.append(SceneInfo(start=scene.start, end=scene.end))
    # 尾段过短 → 并入前邻
    if len(merged) >= 2 and (merged[-1].end - merged[-1].start) < min_duration_s:
        last = merged.pop()
        tail = merged[-1]
        merged[-1] = SceneInfo(start=tail.start, end=last.end)
    # 首段过短且无前邻 → 吸收后邻
    if len(merged) >= 2 and (merged[0].end - merged[0].start) < min_duration_s:
        second = merged.pop(1)
        head = merged[0]
        merged[0] = SceneInfo(start=head.start, end=second.end)
    # 超长均分
    result: list[SceneInfo] = []
    for scene in merged:
        duration = scene.end - scene.start
        if duration <= max_duration_s:
            result.append(scene)
            continue
        parts = int(duration // max_duration_s) + 1
        step = duration / parts
        for index in range(parts):
            result.append(
                SceneInfo(start=scene.start + index * step, end=scene.start + (index + 1) * step)
            )
    return result
