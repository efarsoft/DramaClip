"""B1：显式引擎失败即抛绝不换引擎；未配置/auto 才允许回退，且回退必须留痕。

纪律来源（JJYB）：用户显式选了克隆音色引擎（indextts2/kokoro），合成失败时静默
落到 edge 默认音 = 人设声音变了还查不出来。所以：
- `tts.engine` 是具体引擎名 → 失败直接抛（带引擎名与原因），不试别的引擎；
- 未配置或 `auto` → 按固定顺序回退，每段留 engine_requested/engine_used/
  fallback_used/fallback_reason 的溯源日志（可选 log 回调 + 模块级 logger）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.narration import pipeline
from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    TimelineSegment,
)

_DURATION_S = 1.25
_SOURCE = {"ep1": 120.0}


class _CountingTts:
    """可点名失败的计数替身：calls 记录 (text, voice)，fail=True 时每次合成都抛。"""

    def __init__(self, name: str, *, fail: bool = False) -> None:
        self.name = name
        self.fail = fail
        self.calls: list[tuple[str, Any]] = []

    def synthesize(self, text: str, voice: Any, out_path: Path) -> Path:
        self.calls.append((text, voice))
        if self.fail:
            raise RuntimeError(f"{self.name} 云端不可达")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(text.encode("utf-8"))
        return out_path


def _plan(*texts: str) -> PlanData:
    items = [NarrationText(id=f"n{i}", text=text) for i, text in enumerate(texts)]
    timeline = [
        TimelineSegment(
            episode_id="ep1",
            start=i * 10.0,
            end=i * 10.0 + 8.0,
            audio="narration",
            narration_id=f"n{i}",
        )
        for i in range(len(texts))
    ]
    return PlanData(mode="full_narration", timeline=timeline, narration_texts=items)


def _install(
    monkeypatch: pytest.MonkeyPatch,
    registry: dict[str, _CountingTts],
    created: list[str],
) -> None:
    def fake_create(engine: str, models_dir: Any = None) -> Any:
        created.append(engine)
        if engine not in registry:
            raise ValueError(f"未知 TTS 引擎: {engine}")
        return registry[engine]

    monkeypatch.setattr(pipeline, "create_tts", fake_create)
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", lambda _p: _DURATION_S)


def _run(
    plan: PlanData,
    settings: dict[str, str],
    work_dir: Path,
    log: Any = None,
) -> PlanData:
    return pipeline.synthesize_narration_texts(
        plan, settings, work_dir, source_durations=_SOURCE, log=log
    )


def test_explicit_engine_failure_raises_without_trying_others(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """显式 edge 失败：错误必须带引擎名与原因，且 kokoro/indextts2 一次都不许被碰。"""
    registry = {
        "edge": _CountingTts("edge", fail=True),
        "kokoro": _CountingTts("kokoro"),
        "indextts2": _CountingTts("indextts2"),
    }
    created: list[str] = []
    _install(monkeypatch, registry, created)

    with pytest.raises(RuntimeError, match="合成失败") as info:
        _run(_plan("文案一"), {"tts.engine": "edge"}, tmp_path / "tts")

    assert created == ["edge"], f"显式引擎不许构造别的引擎，实得 {created}"
    assert registry["kokoro"].calls == []
    assert registry["indextts2"].calls == []
    message = str(info.value)
    assert "engine=edge" in message
    assert "云端不可达" in message


def test_explicit_clone_engine_failure_never_lands_on_edge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """JJYB 的核心场景：显式 indextts2（克隆音色）失败绝不静默落到 edge 默认音。"""
    registry = {
        "edge": _CountingTts("edge"),
        "kokoro": _CountingTts("kokoro"),
        "indextts2": _CountingTts("indextts2", fail=True),
    }
    created: list[str] = []
    _install(monkeypatch, registry, created)

    with pytest.raises(RuntimeError, match="合成失败") as info:
        _run(_plan("文案"), {"tts.engine": "indextts2"}, tmp_path / "tts")

    assert created == ["indextts2"]
    assert registry["edge"].calls == []
    assert "engine=indextts2" in str(info.value)


def test_unknown_explicit_engine_raises_before_any_synthesis(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """显式配置了不存在的引擎：当场 ValueError，不许当 auto 处理去回退。"""
    registry = {"edge": _CountingTts("edge")}
    created: list[str] = []
    _install(monkeypatch, registry, created)

    with pytest.raises(ValueError, match="未知 TTS 引擎"):
        _run(_plan("文案"), {"tts.engine": "ghost"}, tmp_path / "tts")
    assert registry["edge"].calls == []


def test_auto_falls_back_and_leaves_trace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """auto：edge 失败 → kokoro 成功；log 回调必须留下完整溯源四元组。"""
    registry = {
        "edge": _CountingTts("edge", fail=True),
        "kokoro": _CountingTts("kokoro"),
        "indextts2": _CountingTts("indextts2"),
    }
    created: list[str] = []
    _install(monkeypatch, registry, created)
    messages: list[tuple[str, str]] = []

    result = _run(
        _plan("文案"),
        {"tts.engine": "auto"},
        tmp_path / "tts",
        log=lambda level, message: messages.append((level, message)),
    )

    assert created[:2] == ["edge", "kokoro"]
    assert registry["indextts2"].calls == [], "kokoro 成功后不该再碰 indextts2"
    audio = result.narration_texts[0]
    assert audio.audio_path is not None
    assert Path(audio.audio_path).read_text(encoding="utf-8") == "文案"
    joined = "\n".join(message for _, message in messages)
    assert "engine_requested=auto" in joined
    assert "engine_used=kokoro" in joined
    assert "fallback_used=True" in joined
    assert "fallback_reason=" in joined
    assert "edge" in joined and "云端不可达" in joined


def test_missing_engine_setting_uses_auto_chain_without_fallback_trace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """未配置 tts.engine：按 auto 处理；首个引擎成功时 fallback_used=False。"""
    registry = {"edge": _CountingTts("edge"), "kokoro": _CountingTts("kokoro")}
    created: list[str] = []
    _install(monkeypatch, registry, created)
    messages: list[tuple[str, str]] = []

    _run(
        _plan("文案"),
        {},
        tmp_path / "tts",
        log=lambda level, message: messages.append((level, message)),
    )

    assert created == ["edge"], "auto 链首必须是 edge（与未配置时的历史默认一致）"
    joined = "\n".join(message for _, message in messages)
    assert "engine_requested=auto" in joined
    assert "engine_used=edge" in joined
    assert "fallback_used=False" in joined


def test_auto_all_engines_fail_raises_with_every_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    registry = {
        "edge": _CountingTts("edge", fail=True),
        "kokoro": _CountingTts("kokoro", fail=True),
        "indextts2": _CountingTts("indextts2", fail=True),
    }
    created: list[str] = []
    _install(monkeypatch, registry, created)

    with pytest.raises(RuntimeError, match="合成失败") as info:
        _run(_plan("文案"), {"tts.engine": "auto"}, tmp_path / "tts")

    assert created == ["edge", "kokoro", "indextts2"]
    message = str(info.value)
    for name in ("edge", "kokoro", "indextts2"):
        assert name in message, f"回退链全员失败的原因必须逐个带出，缺 {name}"


def test_provenance_logged_per_segment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """溯源是每段一条：两段方案必须留下两条 engine_used 记录。"""
    registry = {"edge": _CountingTts("edge")}
    _install(monkeypatch, registry, [])
    messages: list[tuple[str, str]] = []

    _run(
        _plan("第一段", "第二段"),
        {"tts.engine": "edge"},
        tmp_path / "tts",
        log=lambda level, message: messages.append((level, message)),
    )

    used = [m for _, m in messages if "engine_used=" in m]
    assert len(used) == 2
    assert all("engine_requested=edge" in m for m in used)
    assert all("engine_used=edge" in m for m in used)
    assert all("fallback_used=False" in m for m in used)
