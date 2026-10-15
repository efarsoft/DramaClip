"""engines.exporter.ai_label：AI 生成标注（settings export.ai_label，默认关闭）。

业主裁决 2026-10-15：AI 标注由用户决定开启/关闭、默认关闭——本组测试钉住
「默认关」「滤镜串形状」「失败硬失败」三件事。真实 ffmpeg 执行由真机 DoD 覆盖
（同 test_encoder.py 的规矩：命令构建在单测，执行在端到端）。
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from dramaclip.engines.exporter import ai_label, encoder
from dramaclip.infra import config


def test_default_is_off() -> None:
    """DEFAULTS 默认关闭；缺键/旧库同样判假——不许悄悄默认开。"""
    assert config.DEFAULTS["export.ai_label"] == "false"
    assert ai_label.enabled({"export.ai_label": "false"}) is False
    assert ai_label.enabled({"export.ai_label": "true"}) is True
    assert ai_label.enabled({}) is False


def test_encoder_param_defaults_off() -> None:
    """export_plan / _export_plan_once 的 burn_ai_label 默认 False：
    不传就不烧，既有调用点（测试与内部路径）逐字节不变。"""
    for fn in (encoder.export_plan, encoder._export_plan_once):
        param = inspect.signature(fn).parameters["burn_ai_label"]
        assert param.default is False
        assert param.kind is inspect.Parameter.KEYWORD_ONLY


def _drawtext_options(vf: str) -> dict[str, str]:
    """按未被单引号包住的 ':' 切 drawtext 选项（路径值带引号且盘符转义为 \\:）。

    与 tests/infra/ffmpeg/test_cover.py 同款解析（滤镜串里唯一允许出现的
    「裸冒号」就是选项分隔符）。
    """
    body = vf[len("drawtext=") :]
    opts: dict[str, str] = {}
    buf = ""
    in_quotes = False
    for ch in body:
        if ch == "'":
            in_quotes = not in_quotes
            buf += ch
        elif ch == ":" and not in_quotes:
            key, sep, value = buf.partition("=")
            if sep:
                opts[key] = value
            buf = ""
        else:
            buf += ch
    key, sep, value = buf.partition("=")
    if sep:
        opts[key] = value
    return opts


def test_label_vf_shape() -> None:
    """滤镜串形状：drawtext + textfile（CJK 不进滤镜串）+ 右上角定位 + 描边框。"""
    vf = ai_label.label_vf(Path("C:/fonts/Noto.otf"), Path("C:/tmp/label.txt"), (1080, 1920))
    assert vf.startswith("drawtext=")
    opts = _drawtext_options(vf)
    # 路径走真机验证过的转义（单引号 + 盘符 \\:），同封面字层
    assert opts["fontfile"] == "'C\\:/fonts/Noto.otf'"
    assert opts["textfile"] == "'C\\:/tmp/label.txt'"
    assert opts["fontsize"] == "56", "1920/34≈56"
    assert opts["fontcolor"] == "white"
    assert opts["borderw"] == "3"
    assert opts["x"] == "w-text_w-w*0.03", "右上角：右边距 3%"
    assert opts["y"] == "h*0.03", "右上角：上边距 3%"


def _stub_font(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    face = tmp_path / "NotoSansSC-Regular.otf"
    face.write_bytes(b"fake-font")
    monkeypatch.setattr(ai_label.ffmpeg_cover, "bundled_font_face", lambda: face)
    return face


def test_apply_burns_and_replaces(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """开启路径：textfile 写「AI 生成」→ 音频流复制 → 原子替换成片。"""
    _stub_font(monkeypatch, tmp_path)
    work = tmp_path / "work"
    captured: dict[str, object] = {}

    def fake_run(args: list[str], **kwargs: object) -> None:
        captured["args"] = args
        textfiles = list(work.glob(".ai-label-*.txt"))
        assert len(textfiles) == 1
        captured["text"] = textfiles[0].read_text(encoding="utf-8")
        captured["timeout_s"] = kwargs.get("timeout_s")
        Path(args[-1]).write_bytes(b"labeled")  # 产出 staged，让 os.replace 成功

    monkeypatch.setattr(ai_label.runner, "run", fake_run)
    out = tmp_path / "film.mp4"
    out.write_bytes(b"raw")
    ai_label.apply(out, work, (1080, 1920))

    assert out.read_bytes() == b"labeled", "原地替换为烧过标注的成片"
    assert captured["text"] == ai_label.LABEL_TEXT
    assert captured["timeout_s"] == ai_label._TIMEOUT_S
    joined = " ".join(captured["args"])  # type: ignore[arg-type]
    assert "-c:a copy" in joined, "音频流复制：保住 loudness 归一成果"
    assert "-c:v libx264" in joined
    # 临时 textfile 与 staged 都不残留
    assert list(work.glob(".ai-label-*.txt")) == []
    assert not (work / "ai_label_stage.mp4").exists()


def test_apply_ffmpeg_failure_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """ffmpeg 失败 → AiLabelError 上抛（导出记失败），不静默交付无标注成片。"""
    _stub_font(monkeypatch, tmp_path)

    def boom(args: list[str], **kwargs: object) -> None:
        raise ai_label.runner.FfmpegError("encode failed")

    monkeypatch.setattr(ai_label.runner, "run", boom)
    out = tmp_path / "film.mp4"
    out.write_bytes(b"raw")
    with pytest.raises(ai_label.AiLabelError, match="encode failed"):
        ai_label.apply(out, tmp_path / "work", (1080, 1920))
    assert out.read_bytes() == b"raw", "原片不被半成品替换"
    assert not (tmp_path / "work" / "ai_label_stage.mp4").exists()


def test_apply_without_font_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """随包字体缺失同样硬失败：标注是用户明示要买的，不是可降级的增强项。"""
    monkeypatch.setattr(ai_label.ffmpeg_cover, "bundled_font_face", lambda: None)
    out = tmp_path / "film.mp4"
    out.write_bytes(b"raw")
    with pytest.raises(ai_label.AiLabelError, match="字体"):
        ai_label.apply(out, tmp_path / "work", (1080, 1920))
