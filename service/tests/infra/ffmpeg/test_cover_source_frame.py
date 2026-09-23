"""A1：封面从源素材截帧——composition_vf（成片构图链）前置在缩略图 scale/drawtext 之前。

字层能力与 title=None 的旧形状回归在 test_cover.py 钉死；这里只钉新参数：
- 给了 composition_vf：滤镜串 = 构图链 + ",scale=480:-2"（+ drawtext），不含 ass；
- composition_vf=None（默认）：命令与旧形状逐字节一致（test_cover.py 已钉，此处钉
  seek_s 可变时形状仍成立——源截帧的 seek 是首段 start+1.5，不是 1.5）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

import dramaclip.engines.subtitle.caption_font as caption_font_mod
from dramaclip.infra.ffmpeg import cover as cover_engine
from dramaclip.infra.ffmpeg import runner

_COMPOSITION = (
    "scale=1080:1920:force_original_aspect_ratio=increase,"
    "crop=1080:1920:max(0\\,min(iw-1080\\,iw*0.2500-(1080/2))):(ih-1920)/2,"
    "scale=1080:1920"
)


def _vf(args: list[str]) -> str:
    return args[args.index("-vf") + 1]


def _record_runs(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(args: list[str], timeout_s: float = 30) -> None:
        del timeout_s
        calls.append(list(args))
        Path(args[-1]).write_bytes(b"jpg")

    monkeypatch.setattr(runner, "run", fake_run)
    return calls


@pytest.fixture
def bundled_font(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    fonts_dir = tmp_path / "fonts"
    fonts_dir.mkdir()
    face = fonts_dir / "NotoSansSC-Regular.otf"
    face.write_bytes(b"fake-font")

    def fake_caption_font(fonts_dir_arg: Path | None = None) -> caption_font_mod.CaptionFont:
        del fonts_dir_arg
        return caption_font_mod.CaptionFont(family="Noto Sans SC", files_dir=fonts_dir)

    monkeypatch.setattr(caption_font_mod, "caption_font", fake_caption_font)
    return face


def test_composition_chain_prepended_without_title(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """源截帧：构图链前置、缩略图 scale 收尾、不含 ass/drawtext；seek 用给定的源时间戳。"""
    calls = _record_runs(monkeypatch)
    source = tmp_path / "ep1.mp4"
    out = tmp_path / "cover.jpg"
    ok = cover_engine.extract_cover(
        source, out, seek_s=21.5, composition_vf=_COMPOSITION
    )
    assert ok is True
    assert calls[0] == [
        "-y",
        "-ss",
        "21.5",
        "-i",
        str(source),
        "-vframes",
        "1",
        "-vf",
        _COMPOSITION + ",scale=480:-2",
        "-q:v",
        "4",
        "-strict",
        "unofficial",
        str(out),
    ]
    assert "ass=" not in _vf(calls[0])
    assert "drawtext" not in _vf(calls[0])


def test_composition_chain_keeps_three_stages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """三级构图链逐级在位：increase 填充 → crop（跟脸表达式原样）→ 输出分辨率。"""
    calls = _record_runs(monkeypatch)
    out = tmp_path / "cover.jpg"
    assert cover_engine.extract_cover(
        tmp_path / "ep1.mp4", out, seek_s=3.5, composition_vf=_COMPOSITION
    )
    vf = _vf(calls[0])
    assert vf.startswith("scale=1080:1920:force_original_aspect_ratio=increase,")
    assert "crop=1080:1920:max(0\\,min(iw-1080\\,iw*0.2500-(1080/2))):(ih-1920)/2" in vf
    assert ",scale=1080:1920,scale=480:-2" in vf
    assert "eq=" not in vf and "fade" not in vf and "setpts" not in vf


def test_composition_chain_with_title(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bundled_font: Path
) -> None:
    """构图链 + 标题字层共存：drawtext 仍叠在截好的帧上（缩略图 scale 之后）。"""
    del bundled_font
    calls = _record_runs(monkeypatch)
    out = tmp_path / "cover.jpg"
    assert cover_engine.extract_cover(
        tmp_path / "ep1.mp4", out, seek_s=21.5, title="她的反击", composition_vf=_COMPOSITION
    )
    vf = _vf(calls[0])
    assert vf.startswith(_COMPOSITION + ",scale=480:-2,drawtext=")
    assert "textfile=" in vf and "fontfile=" in vf
    assert not list(tmp_path.glob(".cover-title-*"))


def test_composition_none_default_shape_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """默认（不传 composition_vf）：与旧形状逐字节一致，seek_s 可变也不长多余前缀。"""
    calls = _record_runs(monkeypatch)
    video = tmp_path / "film.mp4"
    out = tmp_path / "cover.jpg"
    assert cover_engine.extract_cover(video, out, seek_s=21.5) is True
    assert calls[0] == [
        "-y",
        "-ss",
        "21.5",
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
