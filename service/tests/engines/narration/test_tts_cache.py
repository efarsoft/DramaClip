"""A5：内容寻址合成缓存（tts_dir/cache/）——key=sha256(text|engine|voice|speed)。

与既有「目标 wav 已存在即跳过」共存：目标命中仍走老判据；目标不在而缓存命中时
copy 落位、不再调引擎（VoiceStudio/autoclip 纪律：改一句只重合成一段）。
容量治理 best-effort：超上限按 mtime 淘汰最旧，任何失败都不许 raise。
"""

from __future__ import annotations

import hashlib
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
    def __init__(self, name: str = "edge") -> None:
        self.name = name
        self.calls: list[tuple[str, Any]] = []

    def synthesize(self, text: str, voice: Any, out_path: Path) -> Path:
        self.calls.append((text, voice))
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


def _stub(monkeypatch: pytest.MonkeyPatch, engine: Any) -> None:
    monkeypatch.setattr(pipeline, "create_tts", lambda *a, **k: engine)
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", lambda _p: _DURATION_S)


def _run(
    plan: PlanData,
    tts_dir: Path,
    settings: dict[str, str] | None = None,
) -> PlanData:
    return pipeline.synthesize_narration_texts(
        plan,
        dict(settings or {"tts.engine": "edge"}),
        tts_dir,
        source_durations=_SOURCE,
    )


def _cache_files(tts_dir: Path) -> list[Path]:
    cache = tts_dir / "cache"
    return sorted(p for p in cache.rglob("*") if p.is_file()) if cache.exists() else []


def test_cache_hit_restores_target_without_resynthesising(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """目标文件被清掉（换工作目录/清理产物）后，缓存命中不再调引擎。"""
    engine = _CountingTts()
    _stub(monkeypatch, engine)
    tts_dir = tmp_path / "tts"

    first = _run(_plan("同一句话"), tts_dir)
    assert len(engine.calls) == 1
    assert len(_cache_files(tts_dir)) == 1, "合成成功后必须写缓存"

    # 模拟产物目录被清（缓存目录保留）
    for item in first.narration_texts:
        assert item.audio_path is not None
        Path(item.audio_path).unlink()

    second = _run(_plan("同一句话"), tts_dir)
    assert len(engine.calls) == 1, "缓存命中不该再调引擎"
    audio = second.narration_texts[0]
    assert audio.audio_path is not None
    assert Path(audio.audio_path).read_text(encoding="utf-8") == "同一句话"


def test_cache_survives_across_work_dirs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """缓存目录整体搬到新 tts_dir（真实形态：同 data 下多项目共享缓存）。"""
    engine = _CountingTts()
    _stub(monkeypatch, engine)
    dir_a = tmp_path / "a" / "tts"
    _run(_plan("共享文案"), dir_a)
    assert len(engine.calls) == 1

    dir_b = tmp_path / "b" / "tts"
    dir_b.mkdir(parents=True)
    import shutil

    shutil.copytree(dir_a / "cache", dir_b / "cache")
    _run(_plan("共享文案"), dir_b)
    assert len(engine.calls) == 1, "跨目录缓存必须命中"


@pytest.mark.parametrize(
    ("mutate", "settings_b"),
    [
        ("text", {"tts.engine": "edge", "tts.voice": "甲"}),
        ("voice", {"tts.engine": "edge", "tts.voice": "乙"}),
        ("speed", {"tts.engine": "edge", "tts.voice": "甲", "tts.speed": "1.3"}),
    ],
    ids=["text", "voice", "speed"],
)
def test_any_param_change_is_a_cache_miss(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutate: str,
    settings_b: dict[str, str],
) -> None:
    engine = _CountingTts()
    _stub(monkeypatch, engine)
    tts_dir = tmp_path / "tts"
    _run(_plan("原文案"), tts_dir, {"tts.engine": "edge", "tts.voice": "甲"})
    assert len(engine.calls) == 1

    plan = _plan("改后文案") if mutate == "text" else _plan("原文案")
    _run(plan, tts_dir, settings_b)
    assert len(engine.calls) == 2, f"{mutate} 变了必须缓存不命中、重新合成"


def test_cache_key_is_sha256_of_all_params(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """key 组成的可执行定义：sha256(text|engine|voice|speed) 十六进制即缓存文件名主干。"""
    engine = _CountingTts()
    _stub(monkeypatch, engine)
    tts_dir = tmp_path / "tts"
    _run(
        _plan("文案"),
        tts_dir,
        {"tts.engine": "edge", "tts.voice": "甲", "tts.speed": "1.1"},
    )
    expected = hashlib.sha256("文案|edge|甲|1.1".encode()).hexdigest()
    names = [p.stem for p in _cache_files(tts_dir)]
    assert names == [expected], f"缓存文件名必须是全参数 sha256，实得 {names}"


def test_failed_synthesis_writes_no_cache_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class _Broken:
        def synthesize(self, text: str, voice: Any, out_path: Path) -> Path:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"half")
            raise RuntimeError("断线")

    _stub(monkeypatch, _Broken())
    tts_dir = tmp_path / "tts"
    with pytest.raises(RuntimeError, match="合成失败"):
        _run(_plan("失败文案"), tts_dir)
    assert _cache_files(tts_dir) == [], "失败产物绝不能进缓存"


def test_eviction_shrinks_cache_to_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """超上限按 mtime 淘汰最旧：治理后总大小必须回到上限内，且保留的是最新的。"""
    engine = _CountingTts()
    _stub(monkeypatch, engine)
    tts_dir = tmp_path / "tts"
    # 每条缓存 ~63B（UTF-8）；上限 150B → 只容得下最新 2 条
    monkeypatch.setattr(pipeline, "_CACHE_MAX_BYTES", 150)

    texts = [f"第{i}段" + "垫" * 18 for i in range(4)]
    import time

    for text in texts:
        _run(_plan(text), tts_dir)
        time.sleep(0.02)  # 拉开 mtime，让「淘汰最旧」可判定

    files = _cache_files(tts_dir)
    total = sum(p.stat().st_size for p in files)
    assert total <= 150, f"淘汰后缓存总大小 {total} 仍超上限"
    newest = hashlib.sha256(f"{texts[-1]}|edge||".encode()).hexdigest()
    assert any(p.stem == newest for p in files), "最新写入的缓存条目必须保留"


def test_eviction_failures_never_raise(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """淘汰 best-effort：缓存文件删不掉（被占用/只读）也不许把合成拖下水。"""
    engine = _CountingTts()
    _stub(monkeypatch, engine)
    tts_dir = tmp_path / "tts"
    _run(_plan("先占一条"), tts_dir)
    victim = _cache_files(tts_dir)[0]

    monkeypatch.setattr(pipeline, "_CACHE_MAX_BYTES", 1)  # 逼出淘汰动作

    def _deny_unlink(self: Path, *args: Any, **kwargs: Any) -> None:
        if self == victim:
            raise PermissionError("文件被占用")

    monkeypatch.setattr(Path, "unlink", _deny_unlink)

    result = _run(_plan("再合成一条"), tts_dir)  # 不许抛
    assert result.narration_texts[0].audio_path is not None
