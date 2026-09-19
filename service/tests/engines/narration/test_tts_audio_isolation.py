"""同模式两份方案的音频隔离：stored plan 的 audio_path 必须终身指向它自己的音频。

回归动机：槽位 id 按模式确定性生成（full-1…full-8、intro-1、n0…nK），而
`api/narration.py::_generate_one` 把 `work_dir/"tts"` 这一个目录喂给每个 job、
每个模式、每份方案——旧管线按 `{id}.mp3` 落盘，于是同模式第二次 generate_plans
直接覆盖第一次的音频文件。旧 `narration_plans` 行的 `audio_path` 仍指向那些路径，
之后对旧方案 export.start 就会把**新方案的旁白**混进**旧方案的字幕**，无声报错。
本文件的替身把文案原样写进"音频"文件，断言读文件内容即知"这是谁的音"——
只断言"两条路径不同"抓不住 stale-pointer 回归，内容断言才抓得住。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.narration import pipeline
from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    TimelineSegment,
)

_TTS_DURATION_S = 1.25
_SETTINGS = {"tts.engine": "edge"}


class _TextWritingTts:
    """把文案写进音频文件的替身：文件内容即文案，谁的音一读便知。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._lock = threading.Lock()

    def synthesize(self, text: str, voice: Any, out_path: Path) -> Path:
        if text.strip() == "":  # 真引擎对空文案会失败（ffprobe check=True）：替身必须一样
            raise RuntimeError("TTS 空文案：槽位未被语言层填充")
        with self._lock:
            self.calls.append((text, voice))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(text.encode("utf-8"))
        return out_path


class _PartialFailTts:
    """写了一半就断线的替身：失败方案不许在磁盘上留下任何可被误认成缓存的产物。"""

    def synthesize(self, text: str, voice: Any, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"half-written-mp3")
        raise RuntimeError("云端断线")


def _stub(monkeypatch: pytest.MonkeyPatch, engine: Any) -> None:
    monkeypatch.setattr(pipeline, "create_tts", lambda *a, **k: engine)
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", lambda _p: _TTS_DURATION_S)


def _plan(copy_prefix: str) -> PlanData:
    """同模式同槽位 id 的两段方案：id 确定性重复正是本文件要隔离的东西。"""
    texts = [
        NarrationText(id=f"full-{i}", text=f"{copy_prefix}·第{i}段解说") for i in (1, 2)
    ]
    timeline = [
        TimelineSegment(
            episode_id="ep1",
            start=float(i - 1) * 10.0,
            end=float(i - 1) * 10.0 + 8.0,
            audio="ducked",
            narration_id=f"full-{i}",
        )
        for i in (1, 2)
    ]
    return PlanData(mode="full_narration", timeline=timeline, narration_texts=texts)


def _stored(plan: PlanData) -> PlanData:
    """模拟落库：narration_plans.plan_data 是 JSON 字符串，导出层读的是往返后的那份。"""
    return PlanData.model_validate_json(plan.model_dump_json())


def _synthesize(plan: PlanData, tts_dir: Path, settings: dict[str, str] | None = None) -> PlanData:
    # 源长给 120s：本文件的槽位窗口最晚到 18s，这里是守卫的余量而不是被测对象
    # （判红见 test_backfill_timeline.py）。
    return pipeline.synthesize_narration_texts(
        plan,
        dict(settings or _SETTINGS),
        tts_dir,
        source_durations={"ep1": 120.0},
    )


def test_replanning_same_mode_does_not_corrupt_stored_plan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """核心缺陷：第二次 generate_plans 之后，第一份 stored plan 必须仍能取回自己的音频。

    生产路径里两份方案共用 `work_dir/"tts"`（api/narration.py），旧方案行的
    audio_path 指向的文件一旦被新方案覆盖，export.start 就会拿新旁白配旧字幕。
    """
    engine = _TextWritingTts()
    _stub(monkeypatch, engine)
    tts_dir = tmp_path / "tts"

    first = _stored(_synthesize(_plan("首轮文案"), tts_dir))
    _synthesize(_plan("次轮文案"), tts_dir)

    for text in first.narration_texts:
        assert text.audio_path is not None
        content = Path(text.audio_path).read_text(encoding="utf-8")
        assert content == text.text, (
            f"旧方案 {text.id} 的 audio_path 指向的文件已被新方案覆盖："
            f"文件内容={content!r}，应为其自身文案={text.text!r}"
        )


def test_concurrent_same_mode_jobs_keep_their_own_audio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """并发同模式（_run_generation_parallel 双线程 / produce 与 generate_plans 重叠）。

    确定性说明：不需要真的撞上同一瞬间——旧方案下两线程写**同一个路径**，
    文件最终只能有一份内容，两个方案必有一个读到对方的文案，串行执行也照样红。
    """
    engine = _TextWritingTts()
    _stub(monkeypatch, engine)
    tts_dir = tmp_path / "tts"
    results: dict[str, PlanData] = {}
    errors: list[BaseException] = []

    def run(tag: str) -> None:
        try:
            results[tag] = _synthesize(_plan(tag), tts_dir)
        except BaseException as exc:  # noqa: BLE001 - 线程里的失败要带回主线程断言
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(tag,)) for tag in ("甲方案文案", "乙方案文案")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors, f"并发合成抛出: {errors}"

    for tag, plan in results.items():
        for text in plan.narration_texts:
            assert text.audio_path is not None
            content = Path(text.audio_path).read_text(encoding="utf-8")
            assert content == text.text, f"{tag} 的 {text.id} 读到了别人的音频: {content!r}"


def test_identical_copy_is_synthesised_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """内容寻址即缓存（docs/service/02 §6 factory 行的「缓存优先」）：同文案不二次付费。"""
    engine = _TextWritingTts()
    _stub(monkeypatch, engine)
    tts_dir = tmp_path / "tts"

    first = _synthesize(_plan("同一份文案"), tts_dir)
    calls_after_first = len(engine.calls)
    second = _synthesize(_plan("同一份文案"), tts_dir)

    assert calls_after_first == 2
    assert len(engine.calls) == calls_after_first, "文案未变时第二轮不该再调引擎"
    assert [t.audio_path for t in second.narration_texts] == [
        t.audio_path for t in first.narration_texts
    ]


def test_voice_or_engine_change_never_reuses_the_old_audio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """哈希必须覆盖 voice 与 engine：换了音色/引擎还命中旧文件就是错音。"""
    engine = _TextWritingTts()
    _stub(monkeypatch, engine)
    tts_dir = tmp_path / "tts"

    voice_a = _synthesize(_plan("同文"), tts_dir, {"tts.engine": "edge", "tts.voice": "甲"})
    voice_b = _synthesize(_plan("同文"), tts_dir, {"tts.engine": "edge", "tts.voice": "乙"})
    engine_k = _synthesize(_plan("同文"), tts_dir, {"tts.engine": "kokoro", "tts.voice": "甲"})

    first_paths = [t.audio_path for t in voice_a.narration_texts]
    assert [t.audio_path for t in voice_b.narration_texts] != first_paths, "换 voice 必须换文件"
    assert [t.audio_path for t in engine_k.narration_texts] != first_paths, "换 engine 必须换文件"
    assert len(engine.calls) == 6, "三种 (voice, engine) 组合都该真实合成"


def test_zero_byte_squatter_at_final_path_is_not_a_cache_hit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """缓存命中必须要求非空文件：0 字节的占位残留（历史脏产物）不算合成过。"""
    engine = _TextWritingTts()
    _stub(monkeypatch, engine)
    tts_dir = tmp_path / "tts"
    plan = _plan("占位文案")
    for item in plan.narration_texts:
        squatter = pipeline._content_addressed_audio(
            tts_dir, item.id, item.text, "", "edge"
        )
        squatter.parent.mkdir(parents=True, exist_ok=True)
        squatter.write_bytes(b"")

    result = _synthesize(plan, tts_dir)

    assert len(engine.calls) == 2, "0 字节残留被误当缓存命中，引擎没被调用"
    for text in result.narration_texts:
        assert text.audio_path is not None
        assert Path(text.audio_path).read_text(encoding="utf-8") == text.text


def test_failed_synthesis_leaves_no_audio_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """合成失败不许留半成品：留在最终路径上的半截 mp3 会被下一轮当成缓存命中。"""
    _stub(monkeypatch, _PartialFailTts())
    tts_dir = tmp_path / "tts"

    with pytest.raises(RuntimeError, match="合成失败"):
        _synthesize(_plan("断线文案"), tts_dir)

    leftovers = [p for p in tts_dir.rglob("*") if p.is_file()] if tts_dir.exists() else []
    assert leftovers == [], f"失败的合成在磁盘上留下了: {leftovers}"
