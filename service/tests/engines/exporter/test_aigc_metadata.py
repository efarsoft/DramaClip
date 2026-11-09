"""engines.exporter.aigc_metadata：AIGC 隐式标识（settings export.aigc_metadata，默认关闭）。

业主裁决 2026-11-09：默认关、用户可开。钉住「默认关」「payload 形状（AIGC= 前缀 +
Base64 + 三字段）」「擦源留标参数序」「原子 remux」「收尾遍接线」。
真实 ffmpeg 执行由真机 DoD 覆盖（同 test_ai_label.py 的规矩）。
"""

from __future__ import annotations

import base64
import inspect
import json
from pathlib import Path

import pytest

from dramaclip.engines.exporter import aigc_metadata, encoder
from dramaclip.infra import config


def test_default_is_off() -> None:
    assert config.DEFAULTS["export.aigc_metadata"] == "false"
    assert config.DEFAULTS["export.aigc_producer_code"] == ""
    assert aigc_metadata.enabled({}) is False
    assert aigc_metadata.enabled({"export.aigc_metadata": "true"}) is True


def test_payload_roundtrip() -> None:
    value = aigc_metadata.payload("001191330106MA2C91330100Y43", "export-123")
    decoded = base64.b64decode(value).decode("utf-8")
    assert decoded.startswith("AIGC=")
    doc = json.loads(decoded[len("AIGC="):])
    assert doc == {
        "Label": "1",
        "ContentProducer": "001191330106MA2C91330100Y43",
        "ProduceID": "export-123",
    }


def test_metadata_args_erase_then_write() -> None:
    args = aigc_metadata.metadata_args("P", "C")
    assert args[:2] == ["-map_metadata", "-1"], "先擦源元数据"
    assert args[2] == "-metadata"
    assert args[3].startswith("comment=")
    decoded = base64.b64decode(args[3][len("comment="):]).decode("utf-8")
    assert json.loads(decoded[len("AIGC="):])["ProduceID"] == "C"


def test_stamp_remuxes_atomically(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    film = tmp_path / "film.mp4"
    film.write_bytes(b"old")
    seen: dict[str, object] = {}

    def fake_run(args: list[str], **_kwargs: object) -> None:
        seen["args"] = args
        Path(args[-1]).write_bytes(b"stamped")

    monkeypatch.setattr(aigc_metadata.runner, "run", fake_run)
    aigc_metadata.stamp(film, producer="P", content_id="C")
    assert film.read_bytes() == b"stamped"
    args = seen["args"]
    assert isinstance(args, list)
    assert "-c" in args and "copy" in args, "流复制 remux，不重编"
    assert list(tmp_path.glob("*.part*")) == [], "半成品收走"


def test_stamp_failure_keeps_original(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    film = tmp_path / "film.mp4"
    film.write_bytes(b"old")

    def fake_run(args: list[str], **_kwargs: object) -> None:
        raise RuntimeError("ffmpeg broke")

    monkeypatch.setattr(aigc_metadata.runner, "run", fake_run)
    with pytest.raises(RuntimeError):
        aigc_metadata.stamp(film, producer="P", content_id="C")
    assert film.read_bytes() == b"old"
    assert list(tmp_path.glob("*.part*")) == []


def test_encoder_param_defaults_off() -> None:
    for fn in (encoder.export_plan, encoder._export_plan_once):
        param = inspect.signature(fn).parameters["aigc_stamp"]
        assert param.default is None
        assert param.kind is inspect.Parameter.KEYWORD_ONLY


def test_stamp_runs_at_delivery(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """收尾遍接线：concat 之后才 stamp（单段 copyfile 分支同样覆盖）。"""
    from dramaclip.engines.narration.models import PlanData, TimelineSegment

    source = tmp_path / "ep.mp4"
    source.write_bytes(b"x")
    plan = PlanData(
        mode="raw_clip",
        timeline=[TimelineSegment(episode_id="ep1", start=0.0, end=1.0, audio="original")],
    )
    order: list[str] = []
    monkeypatch.setattr(
        encoder, "_run_cut", lambda args, *_a, **_k: Path(args[-1]).write_bytes(b"seg")
    )

    def fake_concat(_files: list[Path], out: Path) -> None:
        order.append("concat")
        Path(out).write_bytes(b"film")

    monkeypatch.setattr(encoder, "_concat", fake_concat)
    monkeypatch.setattr(
        encoder.aigc_metadata, "stamp",
        lambda film, **_kw: order.append("stamp"),
    )
    out = tmp_path / "out.mp4"
    encoder._export_plan_once(
        plan, {"ep1": str(source)}, out, tmp_path / "work", aigc_stamp=("P", "C")
    )
    assert order == ["concat", "stamp"]

    order.clear()
    encoder._export_plan_once(plan, {"ep1": str(source)}, out, tmp_path / "work2")
    assert order == ["concat"], "不传 aigc_stamp 零额外动作"
