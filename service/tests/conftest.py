"""pytest 共享夹具。"""

from __future__ import annotations

import sqlite3
import subprocess  # noqa: S404 - 参数为受控列表
import weakref
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from dramaclip.infra.storage import db

REPO_ROOT = Path(__file__).resolve().parents[2]


def _ffmpeg() -> str:
    return str(REPO_ROOT / "resources" / "ffmpeg" / "ffmpeg.exe")


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


# 作业线程池登记表：泄漏的作业线程若活过测试，会在 monkeypatch 还原后撞共享模块
# 状态、或在连接关闭后继续写库（use-after-close）——满载偶发红的根源。
_JOB_EXECUTORS: list[weakref.ref[ThreadPoolExecutor]] = []


def register_job_executor(executor: ThreadPoolExecutor) -> ThreadPoolExecutor:
    """作业线程池创建即登记（返回原池，便于内联使用）；memory_db 收尾时统一排空。"""
    _JOB_EXECUTORS.append(weakref.ref(executor))
    return executor


def drain_job_executors() -> None:
    while _JOB_EXECUTORS:
        executor = _JOB_EXECUTORS.pop()()
        if executor is not None:
            executor.shutdown(wait=True)


@pytest.fixture
def memory_db() -> Iterator[sqlite3.Connection]:
    """已迁移的内存库（每个测试独立；与 db.connect 同一串行化形态，
    否则测试测不出生产共享连接上的并发事务互踩）。"""
    conn = sqlite3.connect(
        ":memory:", check_same_thread=False, factory=db.SerializedConnection
    )
    conn.execute("PRAGMA foreign_keys=ON")
    db.migrate(conn)
    yield conn
    # 先排空泄漏作业再关连接：保证它们不会在 close 之后继续持有旧连接，
    # 也不会把本测试的未竟写入带进下一个测试的窗口。
    drain_job_executors()
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
