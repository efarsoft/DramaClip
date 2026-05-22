"""
Pytest 配置文件
提供共享的 fixtures 和测试配置
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from typing import Generator


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """创建临时目录，用于测试"""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def mock_video_path(temp_dir: Path) -> str:
    """创建模拟视频文件"""
    video_path = temp_dir / "test_video.mp4"
    video_path.write_bytes(b"mock video content")
    return str(video_path)


@pytest.fixture
def mock_videos(temp_dir: Path) -> list:
    """创建多个模拟视频文件"""
    videos = []
    for i in range(3):
        video_path = temp_dir / f"test_video_{i}.mp4"
        video_path.write_bytes(f"mock video content {i}".encode())
        videos.append(str(video_path))
    return videos


@pytest.fixture
def sample_segments() -> list:
    """返回示例片段数据"""
    return [
        {
            "video_path": "/path/to/video1.mp4",
            "start_time": 0.0,
            "end_time": 10.0,
            "duration": 10.0,
            "score": 0.9,
            "audio_score": 0.8,
            "emotion_score": 0.9,
            "visual_score": 0.85,
            "rhythm_score": 0.7,
        },
        {
            "video_path": "/path/to/video1.mp4",
            "start_time": 15.0,
            "end_time": 25.0,
            "duration": 10.0,
            "score": 0.75,
            "audio_score": 0.7,
            "emotion_score": 0.8,
            "visual_score": 0.7,
            "rhythm_score": 0.8,
        },
        {
            "video_path": "/path/to/video2.mp4",
            "start_time": 5.0,
            "end_time": 20.0,
            "duration": 15.0,
            "score": 0.85,
            "audio_score": 0.9,
            "emotion_score": 0.75,
            "visual_score": 0.9,
            "rhythm_score": 0.85,
        },
    ]


@pytest.fixture
def sample_config() -> dict:
    """返回示例配置"""
    return {
        "audio_weight": 0.4,
        "emotion_weight": 0.3,
        "visual_weight": 0.2,
        "rhythm_weight": 0.1,
        "threshold": 30,
        "min_scene_len": 2,
        "top_ratio": 0.3,
        "min_segment_duration": 2.0,
        "max_segments_per_episode": 5,
    }
