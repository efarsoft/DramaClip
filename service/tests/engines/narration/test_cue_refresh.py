"""旧配音补词界 + 缓存查找不把词界边车当音频。

启用词界之前的配音没有 .cues.json（那时合成没要词界）。它们命中后补合成一次、只取
词界，音频原件不动——既有方案的时间轴是按它量的。补不到就留着旧音频照常出片。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, cast

import pytest

from dramaclip.engines.narration import synthesis
from dramaclip.engines.tts import base as tts_base

_TEXT = "她慌了，他气坏了。"
_VOICE = "zh-CN-YunxiNeural"
_LEGACY = b"legacy-audio"
_CUES = [
    {"text": "她", "start": 0.1, "end": 0.3},
    {"text": "慌", "start": 0.3, "end": 0.6},
    {"text": "了", "start": 0.6, "end": 0.8},
]


def _sidecar(audio: Path) -> Path:
    return audio.with_name(audio.stem + ".cues.json")


def _read(audio: Path) -> Any:
    return json.loads(_sidecar(audio).read_text(encoding="utf-8"))


class _Tts:
    """替身：新合成的音频内容＝文案的字节，与旧音频不同，才断言得出原件没被换掉。"""

    def __init__(self, cues: list[dict[str, Any]] | None = None, error: Exception | None = None):
        self.calls = 0
        self._cues = cues
        self._error = error

    def synthesize(self, text: str, voice: Any, out_path: Path) -> Path:
        self.calls += 1
        if self._error is not None:
            raise self._error
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(text.encode("utf-8"))
        if self._cues is not None:
            _sidecar(out_path).write_text(
                json.dumps(self._cues, ensure_ascii=False), encoding="utf-8"
            )
        return out_path


def _durations(monkeypatch: pytest.MonkeyPatch, table: dict[bytes, float]) -> None:
    monkeypatch.setattr(
        tts_base, "audio_duration_s", lambda path: table.get(path.read_bytes(), 1.25)
    )


def _legacy(root: Path, name: str = "n0") -> Path:
    audio = root / "tts" / f"{name}.mp3"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(_LEGACY)
    return audio


def _run(engine: _Tts, audio: Path, root: Path, name: str = "edge") -> bool:
    return synthesis._synthesize_into(
        cast(Any, engine), name, _TEXT, _VOICE, "", audio, root / "cache"
    )


def test_legacy_audio_gains_cues_and_keeps_its_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    audio = _legacy(tmp_path)
    engine = _Tts(cues=_CUES)
    _durations(monkeypatch, {})

    did = _run(engine, audio, tmp_path)

    assert did is True, "补词界是真的调了引擎：算力回执要如实记"
    assert engine.calls == 1
    assert audio.read_bytes() == _LEGACY, "旧音频原件不许被换掉"
    assert _read(audio) == _CUES
    assert sorted(p.name for p in audio.parent.iterdir()) == ["n0.cues.json", "n0.mp3"], (
        "暂存文件要收干净"
    )


def test_cues_are_refreshed_at_most_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    audio = _legacy(tmp_path)
    engine = _Tts(cues=_CUES)
    _durations(monkeypatch, {})

    assert _run(engine, audio, tmp_path) is True
    assert _run(engine, audio, tmp_path) is False
    assert engine.calls == 1, "边车已在：同一段不许再补"


@pytest.mark.parametrize(
    ("cues", "lengths"),
    [
        (None, {}),  # 引擎没给词界
        (_CUES, {_TEXT.encode("utf-8"): 2.0}),  # 新旧时长对不上：服务换过发声，词时不认
    ],
    ids=["no-cues", "different-length"],
)
def test_unusable_cues_leave_an_empty_marker_so_there_is_no_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cues: Any, lengths: dict[bytes, float]
) -> None:
    """补过但没有也要留边车：它是「补过了」的记号，缺边车就会每次建方案都重合成一遍。"""
    audio = _legacy(tmp_path)
    engine = _Tts(cues=cues)
    _durations(monkeypatch, lengths)

    assert _run(engine, audio, tmp_path) is True

    assert audio.read_bytes() == _LEGACY
    assert _read(audio) == []
    assert _run(engine, audio, tmp_path) is False
    assert engine.calls == 1


def test_failed_refresh_keeps_the_old_audio_and_backs_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """没网的时候不许每段都等引擎把重试跑完：失败一次，这一轮后面的段都不再补。"""
    first, second = _legacy(tmp_path), _legacy(tmp_path, "n1")
    engine = _Tts(error=RuntimeError("没网"))

    assert _run(engine, first, tmp_path) is False
    assert first.read_bytes() == _LEGACY and not _sidecar(first).exists(), (
        "失败的补词界不许在旧音频旁边留下任何东西"
    )
    assert synthesis._cue_refresh_after > time.monotonic()
    assert _run(engine, second, tmp_path) is False
    assert engine.calls == 1 and second.read_bytes() == _LEGACY


def test_engines_that_never_emit_cues_are_left_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    audio = _legacy(tmp_path)
    engine = _Tts(cues=_CUES)

    assert _run(engine, audio, tmp_path, name="kokoro") is False

    assert engine.calls == 0 and not _sidecar(audio).exists()


def test_cache_lookup_never_returns_the_cue_sidecar(tmp_path: Path) -> None:
    """`<key>.*` 也匹配 `<key>.cues.json`：Windows 目录按字母序它还排在 .mp3 前面。"""
    cache = tmp_path / "cache"
    cache.mkdir()
    key = synthesis._cache_key(_TEXT, "edge", _VOICE, "")
    (cache / f"{key}.cues.json").write_text("[]", encoding="utf-8")
    (cache / f"{key}.mp3").write_bytes(b"cached")

    hit = synthesis._cache_entry_for(cache, _TEXT, "edge", _VOICE, "")

    assert hit == cache / f"{key}.mp3", "把词界边车当成了音频"
    (cache / f"{key}.mp3").unlink()
    assert synthesis._cache_entry_for(cache, _TEXT, "edge", _VOICE, "") is None


def test_cached_audio_without_cues_is_refreshed_and_the_cache_remembers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    key = synthesis._cache_key(_TEXT, "edge", _VOICE, "")
    (cache / f"{key}.mp3").write_bytes(b"cached-legacy")
    audio = tmp_path / "tts" / "n0.mp3"
    audio.parent.mkdir(parents=True)  # 落位目录由调用方先建好（与真实工作目录一致）
    engine = _Tts(cues=_CUES)
    _durations(monkeypatch, {})

    assert _run(engine, audio, tmp_path) is True

    assert audio.read_bytes() == b"cached-legacy", "缓存命中照旧拷音频，补词界只取边车"
    assert _read(audio) == _CUES
    assert _read(cache / f"{key}.mp3") == _CUES, "词界要记回缓存，下一份方案才不用再补"
    # 下一份方案：缓存带着词界命中，引擎一次都不调
    audio.unlink()
    _sidecar(audio).unlink()
    assert _run(engine, audio, tmp_path) is False
    assert engine.calls == 1 and _read(audio) == _CUES
