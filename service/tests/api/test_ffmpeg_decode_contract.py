"""ffmpeg 的输出按 UTF-8 解码，不看系统 locale（契约测试，与跑用例的机器无关）。

背景（2026-11-24 审查复核）：中文 Windows 上 Python 的默认解码是 GBK，而 ffmpeg
写的是 UTF-8——成片路径或元数据里带一个 GBK 解不了的字节序列，读流线程就抛
UnicodeDecodeError、stderr 变 None。静默体检裹着「失败绝不挡导出」的宽捕获，于是
表现成体检悄悄不跑（正是它自己的 docstring 警告过的那种静默）。

仓库里调 ffmpeg 的 21 处早已显式 UTF-8 解码，这两处是漏网的。注意方向：给进程树
全局强制 ``PYTHONIOENCODING=utf-8`` **不是**修法——它会让没钉解码的那几处
变成「子进程写 UTF-8、父进程按 GBK 解」，把一致但受限的现状改成会炸。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import bgm, export_audit


@pytest.mark.parametrize(
    ("func", "args"),
    [
        (export_audit._run_silencedetect, ("D:/成片/第一集.mp4",)),
        (bgm.subprocess_run_ffmpeg, (Path("a.wav"), Path("b.ogg"))),
    ],
    ids=["silencedetect", "wav_to_ogg"],
)
def test_ffmpeg_output_is_decoded_as_utf8(
    monkeypatch: pytest.MonkeyPatch, func: Any, args: tuple[Any, ...]
) -> None:
    seen: dict[str, Any] = {}

    def _fake_run(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        seen.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    func(*args)

    assert seen.get("encoding") == "utf-8", "ffmpeg 的输出必须显式按 UTF-8 解码"
    assert seen.get("errors") == "replace", "解不了的个别字节替换成 �，不许让整段读流炸掉"
