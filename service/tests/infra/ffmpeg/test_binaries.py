"""渲染环节的可观测性：ffmpeg 版本要从真机探测来，就绪度条才有第 ④ 格可说。

真实依据（2026-09-19 本机）：``resources/ffmpeg/ffmpeg.exe -version`` 首行为
``ffmpeg version 8.1.1-essentials_build-www.gyan.dev ...``——本仓库自带的就是它。
"""

from __future__ import annotations

from typing import Any

import pytest

from dramaclip.api import system as system_api
from dramaclip.infra.ffmpeg import binaries
from dramaclip.transport.rpc import Router, RpcRequest


class _Completed:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout


def test_version_parses_the_first_line_header(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> _Completed:
        return _Completed(
            "ffmpeg version 8.1.1-essentials_build-www.gyan.dev Copyright (c) 2000-2026\n"
            "built with gcc 15.2.0"
        )

    monkeypatch.setattr(binaries.subprocess, "run", fake_run)

    assert binaries.version(force=True) == "8.1.1"


def test_version_is_empty_when_no_binary_is_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """找不到 ffmpeg 时返回空串而不是抛错：就绪度条要说「渲染引擎不可用」，不能整页炸。"""

    def explode() -> str:
        raise FileNotFoundError("找不到 ffmpeg")

    monkeypatch.setattr(binaries, "resolve_ffmpeg", explode)

    assert binaries.version(force=True) == ""


def test_version_is_empty_when_the_header_is_unparsable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        binaries.subprocess, "run", lambda *a, **k: _Completed("git: command not found")
    )

    assert binaries.version(force=True) == ""


def test_refresh_replaces_the_value_every_caller_sees(monkeypatch: pytest.MonkeyPatch) -> None:
    """force 的语义是「换掉全机共用的那份缓存」，不是「另开一份带 force 键的缓存」。

    场景是真实的：修好或换掉 ffmpeg 后点「重新检测」，此后所有普通调用（包括别处
    正在渲染的就绪度条）都必须看到新版本，而不是继续报刷前的旧值。
    """
    calls: list[str] = []
    monkeypatch.setattr(binaries, "resolve_ffmpeg", lambda: calls.append("probe") or "ffmpeg")
    header = {"text": "ffmpeg version 7.0-x\n"}
    monkeypatch.setattr(
        binaries.subprocess, "run", lambda *a, **k: _Completed(header["text"])
    )

    assert binaries.version(force=True) == "7.0"
    assert len(calls) == 1
    assert binaries.version() == "7.0"
    assert len(calls) == 1  # 不刷时吃缓存，不重复起进程

    header["text"] = "ffmpeg version 8.1.1-x\n"
    assert binaries.version() == "7.0"  # 缓存生效：机器变了也不自动跟进
    assert binaries.version(force=True) == "8.1.1"
    assert binaries.version() == "8.1.1"  # 刷完之后普通调用也是新值
    assert len(calls) == 2  # 全程只起了两次进程：强刷各一次


def test_real_bundled_binary_reports_a_dotted_version() -> None:
    """真机自证：不 stub，直接量随包 ffmpeg——判据若与它的输出格式脱节，这条会红。"""
    version = binaries.version(force=True)

    assert version != "", "本机 resources/ffmpeg 不可用，就绪度条的渲染格将永远报红"
    assert version[0].isdigit()
    assert len(version.split(".")) >= 2


def test_health_exposes_the_rendering_engine() -> None:
    router = Router()
    system_api.register(router, service_version="t", protocol_version=1, shutdown=lambda: None)

    payload = router.dispatch(RpcRequest(id="h", method="system.health", params={})).result

    assert isinstance(payload["ffmpeg_version"], str)
