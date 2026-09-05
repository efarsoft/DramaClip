"""engines.analysis.scene_detector.detect_scenes：真实镜头切换检测（scenedetect）。"""

from __future__ import annotations

import subprocess  # noqa: S404 - 参数为受控列表
from pathlib import Path

import pytest

from dramaclip.engines.analysis import scene_detector
from dramaclip.engines.analysis.models import SceneInfo

pytest.importorskip("scenedetect")


@pytest.fixture(scope="module")
def cut_video(tmp_path_factory: pytest.TempPathFactory, repo_root: Path) -> Path:
    """两段视觉差异明显的视频拼接（testsrc → smpte 色条），中点有一次硬切。"""
    video = tmp_path_factory.mktemp("cuts") / "cut.mp4"
    ffmpeg = str(repo_root / "resources" / "ffmpeg" / "ffmpeg.exe")
    subprocess.run(  # noqa: S603
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=3:size=320x240:rate=10",
            "-f",
            "lavfi",
            "-i",
            "smptebars=duration=3:size=320x240:rate=10",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[out]",
            "-map",
            "[out]",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(video),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return video


def test_detect_finds_hard_cut(cut_video: Path) -> None:
    scenes = scene_detector.detect_scenes(cut_video)
    assert len(scenes) >= 2, "中点硬切应产生至少两个场景"
    first: SceneInfo = scenes[0]
    assert 2.0 < first.end < 4.0, "第一场景应在切换点附近结束"


def test_merged_output_within_bounds(cut_video: Path) -> None:
    merged = scene_detector.merge_scenes(scene_detector.detect_scenes(cut_video))
    for scene in merged:
        assert 2.0 <= scene.end - scene.start <= 8.0
