"""engines.analysis.scene_detector.merge_scenes：规整洁函数。"""

from __future__ import annotations

from dramaclip.engines.analysis.models import SceneInfo
from dramaclip.engines.analysis.scene_detector import merge_scenes


def test_short_scene_merged_into_previous() -> None:
    scenes = [SceneInfo(start=0, end=5), SceneInfo(start=5, end=5.5), SceneInfo(start=5.5, end=12)]
    merged = merge_scenes(scenes)
    assert [(s.start, s.end) for s in merged] == [(0, 5.5), (5.5, 12)]


def test_last_short_scene_merged_into_previous() -> None:
    merged = merge_scenes([SceneInfo(start=0, end=5), SceneInfo(start=5, end=5.8)])
    assert [(s.start, s.end) for s in merged] == [(0, 5.8)]


def test_long_scene_split_evenly() -> None:
    merged = merge_scenes([SceneInfo(start=0, end=20)])
    assert len(merged) == 3
    assert merged[0].start == 0 and merged[-1].end == 20
    for scene in merged:
        assert 6 < scene.end - scene.start <= 8.1


def test_normal_scenes_untouched() -> None:
    scenes = [SceneInfo(start=0, end=4), SceneInfo(start=4, end=8.5)]
    assert merge_scenes(scenes) == scenes


def test_first_short_scene_absorbs_next() -> None:
    merged = merge_scenes([SceneInfo(start=0, end=1), SceneInfo(start=1, end=5)])
    assert [(s.start, s.end) for s in merged] == [(0, 5)]
