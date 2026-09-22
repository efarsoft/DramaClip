"""成片封面截钩子帧（默认 1.5s）＋可选标题字层（drawtext 烧字）。"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

import dramaclip.engines.subtitle.caption_font as caption_font_mod
from dramaclip.infra.ffmpeg import cover as cover_engine
from dramaclip.infra.ffmpeg import runner


def _vf(args: list[str]) -> str:
    return args[args.index("-vf") + 1]


def _drawtext_options(vf: str) -> dict[str, str]:
    """按未被单引号包住的 ':' 切 drawtext 选项（路径值带引号且盘符转义为 \\:）。"""
    marker = "scale=480:-2,drawtext="
    assert vf.startswith(marker), vf
    body = vf[len(marker) :]
    parts: list[str] = []
    current: list[str] = []
    in_quote = False
    for char in body:
        if char == "'":
            in_quote = not in_quote
            current.append(char)
        elif char == ":" and not in_quote:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    opts: dict[str, str] = {}
    for part in parts:
        key, _, value = part.partition("=")
        opts[key] = value
    return opts


def _unfilter_path(value: str) -> str:
    """还原 caption_font.fontsdir_option 同款转义：单引号 + 盘符 \\:。"""
    assert value.startswith("'") and value.endswith("'"), value
    return value[1:-1].replace("\\:", ":")


@pytest.fixture
def bundled_font(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """把 caption_font() 桩到 tmp 假字体文件（cover 惰性导入，调用时取到补丁）。"""
    fonts_dir = tmp_path / "fonts"
    fonts_dir.mkdir()
    face = fonts_dir / "NotoSansSC-Regular.otf"
    face.write_bytes(b"fake-font")

    def fake_caption_font(fonts_dir_arg: Path | None = None) -> caption_font_mod.CaptionFont:
        del fonts_dir_arg
        return caption_font_mod.CaptionFont(family="Noto Sans SC", files_dir=fonts_dir)

    monkeypatch.setattr(caption_font_mod, "caption_font", fake_caption_font)
    return face


def _record_runs(
    monkeypatch: pytest.MonkeyPatch, *, fail_drawtext: bool = False, always_fail: bool = False
) -> tuple[list[list[str]], list[str]]:
    """monkeypatch runner.run：记录命令；带 drawtext 的命令可桩为失败/读取 textfile 内容。"""
    calls: list[list[str]] = []
    textfile_contents: list[str] = []

    def fake_run(args: list[str], timeout_s: float = 30) -> None:
        del timeout_s
        calls.append(list(args))
        vf = _vf(args)
        if always_fail:
            raise runner.FfmpegError("boom")
        if "drawtext" in vf:
            if fail_drawtext:
                raise runner.FfmpegError("drawtext 不可用")
            opts = _drawtext_options(vf)
            textfile = Path(_unfilter_path(opts["textfile"]))
            textfile_contents.append(textfile.read_text(encoding="utf-8"))
        Path(args[-1]).write_bytes(b"jpg")

    monkeypatch.setattr(runner, "run", fake_run)
    return calls, textfile_contents


def test_extract_cover_seeks_hook_frame_first(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], timeout_s: float = 30) -> None:
        del timeout_s
        calls.append(list(args))
        Path(args[-1]).write_bytes(b"jpg")

    monkeypatch.setattr(runner, "run", fake_run)
    out = tmp_path / "cover.jpg"
    assert cover_engine.extract_cover(tmp_path / "film.mp4", out) is True
    assert calls, "应至少试一次截帧"
    assert "-ss" in calls[0] and "1.5" in calls[0]


def test_title_none_command_identical_to_legacy_shape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """回归钉死：title=None 的命令与旧形状逐项一致（现有调用零改动）。"""
    calls, _ = _record_runs(monkeypatch)
    video = tmp_path / "film.mp4"
    out = tmp_path / "cover.jpg"
    assert cover_engine.extract_cover(video, out) is True
    assert calls[0] == [
        "-y",
        "-ss",
        "1.5",
        "-i",
        str(video),
        "-vframes",
        "1",
        "-vf",
        "scale=480:-2",
        "-q:v",
        "4",
        "-strict",
        "unofficial",
        str(out),
    ]


def test_blank_title_equals_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls, _ = _record_runs(monkeypatch)
    out = tmp_path / "cover.jpg"
    assert cover_engine.extract_cover(tmp_path / "film.mp4", out, title="   ") is True
    assert all("drawtext" not in _vf(args) for args in calls)
    assert not list(tmp_path.glob(".cover-title-*"))


def test_title_burns_drawtext_with_bundled_font_and_textfile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bundled_font: Path
) -> None:
    """给了 title：drawtext + 随包字体 fontfile + textfile（内容即标题），临时文件用完即删。"""
    calls, contents = _record_runs(monkeypatch)
    out = tmp_path / "cover.jpg"
    assert cover_engine.extract_cover(tmp_path / "film.mp4", out, title="她的反击") is True
    assert len(calls) == 1
    opts = _drawtext_options(_vf(calls[0]))
    assert _unfilter_path(opts["fontfile"]) == bundled_font.as_posix()
    assert contents == ["她的反击"]
    # 底部居中、白字黑描边、字号按 480 宽算出的数值（9:16 下 h/12 会横向爆宽）
    assert opts["fontcolor"] == "white"
    assert opts["bordercolor"] == "black@0.9"
    assert int(opts["borderw"]) >= 3
    assert opts["x"] == "(w-text_w)/2"
    assert opts["y"] == "h-text_h-h/16"
    assert 20 <= int(opts["fontsize"]) <= 64
    # 临时 textfile 用完即删
    assert not list(tmp_path.glob(".cover-title-*"))


def test_long_title_splits_two_lines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bundled_font: Path
) -> None:
    del bundled_font
    _, contents = _record_runs(monkeypatch)
    title = "重生之都市修仙归来逆袭打脸全场震撼"  # 17 字，无标点 → 中点硬拆
    assert len(title) == 17
    out = tmp_path / "cover.jpg"
    assert cover_engine.extract_cover(tmp_path / "film.mp4", out, title=title) is True
    assert contents == [f"{title[:9]}\n{title[9:]}"]


def test_long_title_prefers_punctuation_split(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bundled_font: Path
) -> None:
    del bundled_font
    _, contents = _record_runs(monkeypatch)
    title = "重生之都市修仙，归来逆袭全场震撼"  # 16 字，标点恰在中点
    out = tmp_path / "cover.jpg"
    assert cover_engine.extract_cover(tmp_path / "film.mp4", out, title=title) is True
    assert contents == ["重生之都市修仙，\n归来逆袭全场震撼"]


def test_overlong_title_truncated_with_ellipsis(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bundled_font: Path
) -> None:
    del bundled_font
    _, contents = _record_runs(monkeypatch)
    title = "赘婿逆袭之都市修仙归来打脸全场震撼所有人都看傻了这也太狠了吧真的"  # >28 字
    assert len(title) > 28
    out = tmp_path / "cover.jpg"
    assert cover_engine.extract_cover(tmp_path / "film.mp4", out, title=title) is True
    text = contents[0]
    assert text.replace("\n", "") == f"{title[:28]}…"


def test_drawtext_failure_falls_back_to_plain_frame(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    bundled_font: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """带字层 ffmpeg 失败 → 降级无字层截帧，warn 一条，仍返回 True。"""
    del bundled_font
    calls, _ = _record_runs(monkeypatch, fail_drawtext=True)
    out = tmp_path / "cover.jpg"
    with caplog.at_level(logging.WARNING, logger="dramaclip.infra.ffmpeg.cover"):
        assert cover_engine.extract_cover(tmp_path / "film.mp4", out, title="她的反击") is True
    assert any("drawtext" in _vf(args) for args in calls)
    assert _vf(calls[-1]) == "scale=480:-2"
    assert "标题" in caplog.text
    assert not list(tmp_path.glob(".cover-title-*"))


def test_font_missing_falls_back_to_plain_frame(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """随包字体缺失 → 不烧字层，降级无字层截帧，warn 一条，仍返回 True。"""
    monkeypatch.setattr(
        caption_font_mod,
        "caption_font",
        lambda fonts_dir=None: (_ for _ in ()).throw(FileNotFoundError("字体缺失")),
    )
    calls, _ = _record_runs(monkeypatch)
    out = tmp_path / "cover.jpg"
    with caplog.at_level(logging.WARNING, logger="dramaclip.infra.ffmpeg.cover"):
        assert cover_engine.extract_cover(tmp_path / "film.mp4", out, title="她的反击") is True
    assert all("drawtext" not in _vf(args) for args in calls)
    assert "标题" in caplog.text


def test_all_attempts_fail_returns_false_never_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    bundled_font: Path,
) -> None:
    del bundled_font
    calls, _ = _record_runs(monkeypatch, always_fail=True)
    out = tmp_path / "cover.jpg"
    assert cover_engine.extract_cover(tmp_path / "film.mp4", out, title="她的反击") is False
    # 带字层三段 seek + 无字层三段 seek
    assert len(calls) == 6
    assert not list(tmp_path.glob(".cover-title-*"))
