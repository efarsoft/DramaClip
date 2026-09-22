"""批次二：hook 槽位对齐策略机（JJYB 三段式规则，落点适配「时长服从故事」）。

DramaClip 全片只有一个硬槽位：intro_narration 首段（narration_id=intro-1）被
modes._fit_duration 钳到 _INTRO_MAX_S。策略机只约束这个槽位——实测 TTS 时长
超槽位 ≤1.5 倍时一次 atempo 变速压进槽位（变速不变调），超过 1.5 倍拒绝自动
变速（听感优先），任何 ffmpeg 失败保留原音频 + warn，绝不 raise（这是 hook
节奏优化，不是正确性门禁）。非槽位段（narration 时长=实测音频）绝不变速。

atempo 用打桩的 runner.run 验证，不真跑 ffmpeg（与既有测试同口径）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.narration import modes, pipeline
from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    TimelineSegment,
)
from dramaclip.infra.ffmpeg.runner import FfmpegError, FfmpegResult

_SLOT_S = modes._INTRO_MAX_S  # 30.0：与 intro_first 首段钳制同源
_SOURCE = {"ep1": 3600.0}


class _StubTts:
    def synthesize(self, text: str, voice: str | None, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(text.encode("utf-8"))
        return out_path


class _RunRecorder:
    """记录 runner.run 调用并模拟 atempo 落盘（写个非空派生文件即可）。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.fail = fail

    def __call__(self, args: list[str], **kwargs: Any) -> FfmpegResult:
        self.calls.append(args)
        if self.fail:
            raise FfmpegError("ffmpeg 退出码 1：atempo 炸了", returncode=1)
        out = Path(args[-1])
        out.write_bytes(b"tempo")
        return FfmpegResult(returncode=0, stderr_tail="", seconds_processed=None)


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    measured_s: float,
    retimed_s: float | None = None,
    fail: bool = False,
) -> _RunRecorder:
    """桩掉 TTS 合成、时长探测与 ffmpeg runner。

    时长探测按路径分流：`-atempo` 派生文件报 retimed_s，原始目标报 measured_s。
    retimed_s=None 表示变速失败路径，探测不该被派生文件触发。
    """

    def probe(path: Path) -> float:
        if Path(path).stem.endswith("-atempo"):
            assert retimed_s is not None, "变速产物不该存在却被复测"
            return retimed_s
        return measured_s

    recorder = _RunRecorder(fail=fail)
    monkeypatch.setattr(pipeline, "create_tts", lambda *a, **k: _StubTts())
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", probe)
    monkeypatch.setattr(pipeline.ffmpeg_runner, "run", recorder)
    return recorder


def _intro_plan(hook_id: str = modes._INTRO_SLOT_ID) -> PlanData:
    """intro_narration 形状：首段 hook（硬槽位）+ 原声段。"""
    return PlanData(
        mode="intro_narration",
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=0.0, end=_SLOT_S, audio="narration",
                narration_id=hook_id,
            ),
            TimelineSegment(episode_id="ep1", start=_SLOT_S, end=90.0, audio="original"),
        ],
        narration_texts=[NarrationText(id=hook_id, text="开场钩子文案")],
    )


def _run(
    plan: PlanData, tmp_path: Path, log: list[tuple[str, str]] | None = None
) -> PlanData:
    return pipeline.synthesize_narration_texts(
        plan,
        {"tts.engine": "edge"},
        tmp_path,
        source_durations=_SOURCE,
        log=(lambda level, message: log.append((level, message))) if log is not None else None,
    )


def test_within_slot_keeps_original_audio_untouched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ratio ≤ 1.0：不动音频、不碰 ffmpeg，留 decision=keep 溯源。"""
    recorder = _install(monkeypatch, measured_s=_SLOT_S * 0.8)
    messages: list[tuple[str, str]] = []

    result = _run(_intro_plan(), tmp_path, messages)

    assert recorder.calls == [], "槽位内绝不变速"
    audio = result.narration_texts[0]
    assert audio.audio_path is not None
    assert not audio.audio_path.endswith("-atempo.mp3")
    assert audio.duration == pytest.approx(_SLOT_S * 0.8)
    joined = "\n".join(m for _, m in messages)
    assert "decision=keep" in joined and "intro-1" in joined


def test_ratio_1_1_retimes_once_into_the_slot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """1.0 < ratio ≤ 1.15：一次 atempo（变速不变调），复测通过则用变速产物。"""
    measured = _SLOT_S * 1.1  # 33s
    recorder = _install(monkeypatch, measured_s=measured, retimed_s=_SLOT_S)
    messages: list[tuple[str, str]] = []

    result = _run(_intro_plan(), tmp_path, messages)

    assert len(recorder.calls) == 1, "只许一次 atempo"
    args = recorder.calls[0]
    assert f"atempo={measured / _SLOT_S:.6f}" in args, "atempo 系数=实测/槽位"
    assert "-i" in args and args[0] != "-progress"
    audio = result.narration_texts[0]
    assert audio.audio_path is not None
    assert audio.audio_path.endswith("-atempo.mp3"), "变速产物是派生文件，不回写内容寻址目标"
    assert audio.duration == pytest.approx(_SLOT_S)
    hook = result.timeline[0]
    assert hook.end - hook.start == pytest.approx(_SLOT_S), "回填用变速后的实测时长"
    joined = "\n".join(m for _, m in messages)
    assert "decision=atempo" in joined
    assert all(level == "info" for level, m in messages if "decision=atempo" in m)


def test_ratio_1_3_still_over_slot_after_retime_warns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """1.15 < ratio ≤ 1.5：变速后复测仍超槽位 → 接受现状但必须 warn（诚实失败）。"""
    recorder = _install(monkeypatch, measured_s=_SLOT_S * 1.3, retimed_s=_SLOT_S * 1.05)
    messages: list[tuple[str, str]] = []

    result = _run(_intro_plan(), tmp_path, messages)

    assert len(recorder.calls) == 1
    audio = result.narration_texts[0]
    assert audio.duration == pytest.approx(_SLOT_S * 1.05), "变短了的产物仍然采用"
    warns = [m for level, m in messages if level == "warn"]
    assert any("仍超槽位" in m for m in warns), f"复测仍超必须 warn，实得 {messages}"


def test_ratio_1_8_refuses_retime_and_warns_with_numbers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ratio > 1.5：拒绝自动变速（听感优先），保留原音频，warn 带实测/槽位/ratio。"""
    recorder = _install(monkeypatch, measured_s=_SLOT_S * 1.8)
    messages: list[tuple[str, str]] = []

    result = _run(_intro_plan(), tmp_path, messages)

    assert recorder.calls == [], "拒绝档绝不碰 ffmpeg"
    audio = result.narration_texts[0]
    assert audio.duration == pytest.approx(_SLOT_S * 1.8)
    assert audio.audio_path is not None and not audio.audio_path.endswith("-atempo.mp3")
    warns = [m for level, m in messages if level == "warn"]
    assert len(warns) == 1
    message = warns[0]
    assert "decision=reject" in message
    assert f"{_SLOT_S * 1.8:.2f}" in message and f"{_SLOT_S:.2f}" in message
    assert "1.80" in message, "ratio 要写进日志让人知道该改文案或换音色"


def test_atempo_failure_keeps_original_and_never_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ffmpeg 失败：保留原音频 + warn，不 raise——节奏优化不是正确性门禁。"""
    recorder = _install(monkeypatch, measured_s=_SLOT_S * 1.1, fail=True)
    messages: list[tuple[str, str]] = []

    result = _run(_intro_plan(), tmp_path, messages)

    assert len(recorder.calls) == 1
    audio = result.narration_texts[0]
    assert audio.duration == pytest.approx(_SLOT_S * 1.1)
    assert audio.audio_path is not None and not audio.audio_path.endswith("-atempo.mp3")
    warns = [m for level, m in messages if level == "warn"]
    assert any("atempo" in m or "变速失败" in m for m in warns)


def test_non_slot_segments_never_retime_at_any_ratio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """非槽位段时长服从故事：普通 n0 段再超也不许引入任何 atempo。"""
    recorder = _install(monkeypatch, measured_s=_SLOT_S * 1.8)
    plan = PlanData(
        mode="full_narration",
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=0.0, end=8.0, audio="ducked", narration_id="n0"
            )
        ],
        narration_texts=[NarrationText(id="n0", text="正文旁白")],
    )
    messages: list[tuple[str, str]] = []

    result = _run(plan, tmp_path, messages)

    assert recorder.calls == [], "非槽位段任何 ratio 都不变速"
    assert result.narration_texts[0].duration == pytest.approx(_SLOT_S * 1.8)
    assert not any("对齐策略" in m for _, m in messages), "非槽位段不该有策略机留痕"


def test_script_hook_n0_is_not_a_hard_slot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """dialogue_narration 的 n0 钩子没有硬槽位（长度=实测音频），同样绝不变速。"""
    recorder = _install(monkeypatch, measured_s=_SLOT_S * 1.4)
    plan = PlanData(
        mode="dialogue_narration",
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=0.0, end=5.0, audio="narration", narration_id="n0"
            )
        ],
        narration_texts=[NarrationText(id="n0", text="钩子")],
    )

    result = _run(plan, tmp_path)

    assert recorder.calls == []
    assert result.narration_texts[0].duration == pytest.approx(_SLOT_S * 1.4)


def test_cache_never_receives_the_retimed_product(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """变速产物不进内容寻址缓存：缓存 key 没有变速维度，进去就是同 key 不同字节。"""
    _install(monkeypatch, measured_s=_SLOT_S * 1.1, retimed_s=_SLOT_S)

    _run(_intro_plan(), tmp_path)

    cache_files = list((tmp_path / "cache").glob("*"))
    assert cache_files, "原始合成应正常入缓存"
    for entry in cache_files:
        assert entry.read_bytes() != b"tempo", f"变速产物混进了缓存条目 {entry.name}"
