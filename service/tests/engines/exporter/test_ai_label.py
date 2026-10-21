"""engines.exporter.ai_label：AI 生成标注（settings export.ai_label，默认关闭）。

业主裁决 2026-10-15：AI 标注由用户决定开启/关闭、默认关闭——本组测试钉住
「默认关」「滤镜串形状」「字体缺失硬失败」「段滤镜而非整片后处理」几件事。
真实 ffmpeg 执行由真机 DoD 覆盖（同 test_encoder.py 的规矩：命令构建在单测，
执行在端到端）。
"""

from __future__ import annotations

import inspect
import random
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


def test_prepare_writes_textfile_and_fingerprint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_font(monkeypatch, tmp_path)
    work = tmp_path / "work"
    spec = ai_label.prepare(work, (1080, 1920))
    assert spec.textfile == work / ".ai-label.txt"
    assert spec.textfile.read_text(encoding="utf-8") == ai_label.LABEL_TEXT
    assert spec.vf.startswith("drawtext=")
    assert len(spec.fingerprint) == 64
    assert str(spec.textfile) not in spec.fingerprint, "临时路径不进签名"
    assert list(work.glob(".ai-label-*.txt")) == [], "固定文件名，不留临时文件"


def test_prepare_fingerprint_tracks_font_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """换字体文件内容必须换签名：否则段级复用会拿旧字体的成片顶上。"""
    face = _stub_font(monkeypatch, tmp_path)
    first = ai_label.prepare(tmp_path / "work", (1080, 1920))
    face.write_bytes(b"another-font")
    second = ai_label.prepare(tmp_path / "work", (1080, 1920))
    assert first.fingerprint != second.fingerprint


def test_prepare_without_font_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ai_label.ffmpeg_cover, "bundled_font_face", lambda: None)
    with pytest.raises(ai_label.AiLabelError, match="字体"):
        ai_label.prepare(tmp_path, (1080, 1920))


def test_ai_label_is_a_segment_filter_not_a_post_pass() -> None:
    assert not hasattr(ai_label, "apply"), "整片后处理必须删除"
    args = encoder.cut_segment_args(
        "src.mp4", "out.mp4", start=0, end=1, audio="original", tts_audio=None,
        rng=random.Random(7), ai_label_vf="drawtext=textfile=x",
    )
    vf = args[args.index("-vf") + 1]
    assert "drawtext=textfile=x" in vf, "标注必须进段滤镜，随 Phase B 流复制拼接"


def test_ai_label_fingerprint_enters_the_segment_signature(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """开启标注时内容摘要必须进签名（换文案/字体要重编）；关闭时键缺席，旧缓存不失效。"""
    from dramaclip.engines.narration.models import PlanData, TimelineSegment

    _stub_font(monkeypatch, tmp_path)
    source = tmp_path / "ep.mp4"
    source.write_bytes(b"x")
    plan = PlanData(
        mode="raw_clip",
        timeline=[TimelineSegment(episode_id="ep1", start=0.0, end=1.0, audio="original")],
    )
    monkeypatch.setattr(
        encoder, "_run_cut", lambda args, *_a, **_k: Path(args[-1]).write_bytes(b"seg")
    )
    monkeypatch.setattr(
        encoder, "_concat", lambda _files, out: Path(out).write_bytes(b"film")
    )

    on_work = tmp_path / "on"
    encoder._export_plan_once(
        plan, {"ep1": str(source)}, tmp_path / "on.mp4", on_work, burn_ai_label=True
    )
    on_sig = encoder._read_sig(on_work / "seg_000.mp4")
    assert on_sig is not None
    assert len(str(on_sig["inputs"]["ai_label"])) == 64

    off_work = tmp_path / "off"
    encoder._export_plan_once(
        plan, {"ep1": str(source)}, tmp_path / "off.mp4", off_work, burn_ai_label=False
    )
    off_sig = encoder._read_sig(off_work / "seg_000.mp4")
    assert off_sig is not None
    assert "ai_label" not in off_sig["inputs"]
