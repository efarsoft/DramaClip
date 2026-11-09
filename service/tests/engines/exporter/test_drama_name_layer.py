"""engines.exporter.drama_name_layer：剧名常驻层（settings export.drama_name_layer，默认关闭）。

业主裁决 2026-11-09：默认关、用户可开（报告「推广模式默认开」不采纳）。
镜像 test_ai_label.py 的钉法：默认关/滤镜形状（左上角避让 AI 角标）/
空剧名与缺字体硬失败/段滤镜/签名键缺席兼容。
"""

from __future__ import annotations

import inspect
import random
from pathlib import Path

import pytest

from dramaclip.engines.exporter import drama_name_layer, encoder
from dramaclip.infra import config


def test_default_is_off() -> None:
    assert config.DEFAULTS["export.drama_name_layer"] == "false"
    assert drama_name_layer.enabled({}) is False
    assert drama_name_layer.enabled({"export.drama_name_layer": "true"}) is True


def test_encoder_param_defaults_off() -> None:
    for fn in (encoder.export_plan, encoder._export_plan_once):
        param = inspect.signature(fn).parameters["burn_drama_name"]
        assert param.default is None
        assert param.kind is inspect.Parameter.KEYWORD_ONLY
    param = inspect.signature(encoder.cut_segment_args).parameters["drama_name_vf"]
    assert param.default is None


def _drawtext_options(vf: str) -> dict[str, str]:
    body = vf[len("drawtext="):]
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


def test_layer_vf_top_left() -> None:
    vf = drama_name_layer.layer_vf(Path("C:/fonts/Noto.otf"), Path("C:/tmp/name.txt"), (1080, 1920))
    opts = _drawtext_options(vf)
    assert opts["fontfile"] == "'C\\:/fonts/Noto.otf'"
    assert opts["textfile"] == "'C\\:/tmp/name.txt'"
    assert opts["fontsize"] == "48", "1920/40=48，比 AI 标注小一号"
    assert opts["x"] == "w*0.03", "左上角：与右上角 AI 标注避让"
    assert opts["y"] == "h*0.03"


def _stub_font(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    face = tmp_path / "NotoSansSC-Regular.otf"
    face.write_bytes(b"fake-font")
    monkeypatch.setattr(drama_name_layer.ffmpeg_cover, "bundled_font_face", lambda: face)
    return face


def test_prepare_textfile_and_fingerprint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _stub_font(monkeypatch, tmp_path)
    work = tmp_path / "work"
    spec = drama_name_layer.prepare(work, (1080, 1920), " 大明王朝 ")
    assert spec.textfile == work / ".drama-name.txt"
    assert spec.textfile.read_text(encoding="utf-8") == "大明王朝", "strip 后写入"
    assert len(spec.fingerprint) == 64
    assert str(spec.textfile) not in spec.fingerprint


def test_prepare_tracks_name_and_font(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    face = _stub_font(monkeypatch, tmp_path)
    first = drama_name_layer.prepare(tmp_path / "w", (1080, 1920), "剧A")
    second = drama_name_layer.prepare(tmp_path / "w", (1080, 1920), "剧B")
    assert first.fingerprint != second.fingerprint
    face.write_bytes(b"another-font")
    third = drama_name_layer.prepare(tmp_path / "w", (1080, 1920), "剧A")
    assert first.fingerprint != third.fingerprint


def test_empty_name_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _stub_font(monkeypatch, tmp_path)
    with pytest.raises(drama_name_layer.DramaNameLayerError, match="剧名"):
        drama_name_layer.prepare(tmp_path, (1080, 1920), "  ")


def test_missing_font_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(drama_name_layer.ffmpeg_cover, "bundled_font_face", lambda: None)
    with pytest.raises(drama_name_layer.DramaNameLayerError, match="字体"):
        drama_name_layer.prepare(tmp_path, (1080, 1920), "大明王朝")


def test_is_segment_filter() -> None:
    args = encoder.cut_segment_args(
        "src.mp4", "out.mp4", start=0, end=1, audio="original", tts_audio=None,
        rng=random.Random(7), drama_name_vf="drawtext=textfile=name",
    )
    vf = args[args.index("-vf") + 1]
    assert "drawtext=textfile=name" in vf


def test_fingerprint_enters_signature(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
    monkeypatch.setattr(encoder, "_concat", lambda _files, out: Path(out).write_bytes(b"film"))

    on_work = tmp_path / "on"
    encoder._export_plan_once(
        plan, {"ep1": str(source)}, tmp_path / "on.mp4", on_work, burn_drama_name="大明王朝"
    )
    on_sig = encoder._read_sig(on_work / "seg_000.mp4")
    assert on_sig is not None
    assert len(str(on_sig["inputs"]["drama_name"])) == 64

    off_work = tmp_path / "off"
    encoder._export_plan_once(plan, {"ep1": str(source)}, tmp_path / "off.mp4", off_work)
    off_sig = encoder._read_sig(off_work / "seg_000.mp4")
    assert off_sig is not None
    assert "drama_name" not in off_sig["inputs"], "关闭时键缺席，旧缓存不失效"
