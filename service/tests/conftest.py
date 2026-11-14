"""pytest 共享夹具。"""

from __future__ import annotations

import os
import sqlite3
import subprocess  # noqa: S404 - 参数为受控列表
import weakref
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from dramaclip.engines.narration import variant_scoring
from dramaclip.engines.semantic import llm_quota
from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg
from dramaclip.infra.storage import db

REPO_ROOT = Path(__file__).resolve().parents[2]

# CI 的 torch 是 CPU 轮，开发机常带可用 CUDA：设备相关用例（真算探针/回退）在两边
# 走的是不同分支，本机绿不等于 CI 绿（2026-11-13 实锤：失效桩被可用 GPU 掩蔽，
# 只在 CI 上红）。pytest 会话默认隐藏 GPU 与 CI 同口径；要拿真卡做临时验证时设
# DRAMACLIP_TEST_REAL_GPU=1。须赶在任何用例触发 CUDA 初始化之前生效。
if not os.environ.get("DRAMACLIP_TEST_REAL_GPU"):
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"


def _ffmpeg() -> str:
    # 经产品解析器取二进制：resources 优先、PATH 兜底（Linux CI 用系统 ffmpeg），
    # 测试与生产永远同一套选路逻辑。
    return resolve_ffmpeg()


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(autouse=True)
def _llm_side_channels_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM 侧通道默认不连网（方案评分、额度预检）；专测它们的用例自行打桩（后打的赢）。

    这两处读的是各自模块的绑定，不在各文件 LLM 桩覆盖内——规划链与导出链的
    端到端用例都会触发：对测试假域名发真请求，再吃网络类退避（每次 5s+15s，
    CI 实锤）。
    """

    def _refuse_client(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("测试默认不连 LLM 端点（要测的用例请自行打桩）")

    monkeypatch.setattr(variant_scoring, "client_for", _refuse_client)
    monkeypatch.setattr(llm_quota, "probe_quota", lambda _config: llm_quota.SKIPPED)


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
