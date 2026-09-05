"""pytest 共享夹具。"""

from __future__ import annotations

import sqlite3
import subprocess  # noqa: S404 - 参数为受控列表
from collections.abc import Iterator
from pathlib import Path

import pytest

from dramaclip.infra.storage import db

REPO_ROOT = Path(__file__).resolve().parents[2]


def _ffmpeg() -> str:
    return str(REPO_ROOT / "resources" / "ffmpeg" / "ffmpeg.exe")


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def memory_db() -> Iterator[sqlite3.Connection]:
    """已迁移的内存库（每个测试独立；与 db.connect 同参数保证跨线程行为一致）。"""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA foreign_keys=ON")
    db.migrate(conn)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """3 秒带正弦音轨的测试视频（真实 ffmpeg 生成，供 probe/管线/扫描共用）。"""
    video = tmp_path_factory.mktemp("media") / "sample-ep01.mp4"
    subprocess.run(  # noqa: S603
        [
            _ffmpeg(),
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
            "sine=frequency=440:duration=3",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            str(video),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return video
