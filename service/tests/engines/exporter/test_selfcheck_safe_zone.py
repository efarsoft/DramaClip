"""selfcheck.run 成绩单含 safe_zone 灰项；不进 overall_state 汇总。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dramaclip.engines.exporter import selfcheck


def test_run_payload_includes_safe_zone(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(selfcheck, "measure_audio_video", lambda _v: (-20.0, 0.0))
    payload = selfcheck.run(
        tmp_path / "f.mp4",
        measured_s=10.0, has_audio=True, mode="full_narration",
        budget_s=10.0, planned_segments=2, caption_band=(0.80, 0.92),
    )
    assert payload["safe_zone"]["pass"] is None
    assert "底部互动区" in payload["safe_zone"]["reason"]
    assert selfcheck.overall_state(payload) != "failed", "safe_zone 不进汇总判据"
