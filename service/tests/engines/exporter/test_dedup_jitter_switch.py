"""微扰动开关（2026-11-18 业主裁决）：默认关=恒等参数走原滤镜链（同输入渲染
确定），显式开=扰动照旧；成绩单 v4 如实记录开启与否（成片可自证）。"""

from __future__ import annotations

import random

from dramaclip.engines.dedup import params as dedup_params
from dramaclip.engines.exporter import encoder


def _args(jitter_enabled: bool) -> list[str]:
    return encoder.cut_segment_args(
        "src.mp4",
        "seg_000.mp4",
        start=1.0,
        end=4.0,
        audio="narration",
        tts_audio="tts.mp3",
        rng=random.Random(7),
        jitter_enabled=jitter_enabled,
    )


def test_default_off_yields_identity_chain() -> None:
    """默认关（产品语义）：恒等参数——无 eq 扰动值、setpts 恒速、scale=画布尺寸。"""
    args = _args(False)
    joined = " ".join(args)
    assert "eq=contrast=1.0:brightness=0.0" in joined
    assert "setpts=PTS/1.0" in joined
    # 微缩放上界 0.988——恒等缩放的宽必须等于画布宽（1080），不是缩小值
    assert "scale=1080:1920" in joined
    assert "setpts=PTS/0.9" not in joined


def test_explicit_on_keeps_jitter() -> None:
    """显式开：扰动照旧（speed 落在微变速区间、eq 带非恒等对比值）。"""
    args = _args(True)
    joined = " ".join(args)
    assert "eq=contrast=1.0:brightness=0.0" not in joined
    assert "setpts=PTS/1.0" not in joined


def test_neutral_params_are_identity() -> None:
    """neutral() 与 changed 判据自洽：恒等参数 changed=False。"""
    p = dedup_params.neutral()
    assert not p.changed
    assert dedup_params.generate(random.Random(1)).changed


def test_selfcheck_v4_records_dedup_flag(
    tmp_path,
    monkeypatch,
) -> None:
    """成绩单 v4：dedup_jitter 如实记录（开关状态，不猜不粉饰）。"""
    from dramaclip.engines.exporter import selfcheck

    monkeypatch.setattr(selfcheck, "measure_audio_video", lambda _v: (-20.0, 0.0))
    monkeypatch.setattr(selfcheck, "measure_opening_audio", lambda _v: -20.0)
    monkeypatch.setattr(selfcheck, "measure_avsync_offsets", lambda *_a, **_k: [])
    monkeypatch.setattr(selfcheck, "check_loudness", lambda *_a, **_k: None)
    payload = selfcheck.run(
        tmp_path / "out.mp4",
        measured_s=60.0,
        has_audio=True,
        mode="full_narration",
        budget_s=None,
        planned_segments=1,
        dedup_jitter=True,
    )
    assert payload["version"] == 4
    assert payload["dedup_jitter"] is True
