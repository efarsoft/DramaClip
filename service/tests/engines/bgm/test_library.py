"""engines.bgm.library：扫描（子目录=情绪第一真相源、前缀兜底、manifest、降级）。"""

from __future__ import annotations

import json
import math
import struct
import wave
from pathlib import Path

import pytest

from dramaclip.engines.bgm import library
from dramaclip.engines.bgm.library import BgmTrack, scan_library


def _write_wav(path: Path, seconds: float = 1.0, freq: float = 440.0) -> None:
    """合成单声道 16k wav：ffprobe 能测时长、librosa 能解码的最小真音频。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 16000
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        frames = bytearray()
        for i in range(int(rate * seconds)):
            sample = int(12000 * math.sin(2 * math.pi * freq * i / rate))
            frames.extend(struct.pack("<h", sample))
        wav.writeframes(bytes(frames))


@pytest.fixture
def fake_bpm(monkeypatch: pytest.MonkeyPatch):
    """bpm 测量桩：文件名含 'n bpm' 记号→该值；否则 None（隔离 librosa 的不确定性）。"""

    def _fake(path: Path) -> float | None:
        for token in path.stem.split("_"):
            if token.startswith("bpm"):
                return float(token[3:])
        return None

    monkeypatch.setattr(library, "_measure_bpm", _fake)


# ---------- 子目录=情绪第一真相源 ----------


def test_folder_name_is_emotion(tmp_path: Path, fake_bpm: object) -> None:
    root = tmp_path / "bgm"
    _write_wav(root / "suspense" / "a_bpm110.wav")
    _write_wav(root / "anger" / "b.wav")
    result = scan_library(root)
    by_name = {track.file.name: track for track in result.tracks}
    assert by_name["a_bpm110.wav"].emotion == "suspense"
    assert by_name["b.wav"].emotion == "anger"
    assert result.skipped == []


def test_folder_beats_filename_prefix(tmp_path: Path, fake_bpm: object) -> None:
    """同一文件两处都有信号：子目录名优先（文件夹是人的显式归类动作）。"""
    root = tmp_path / "bgm"
    _write_wav(root / "sadness" / "triumph_01.wav")
    (track,) = scan_library(root).tracks
    assert track.emotion == "sadness"


def test_invalid_folder_name_falls_to_default_with_note(
    tmp_path: Path, fake_bpm: object, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "bgm"
    _write_wav(root / "suspence" / "typo.wav")  # 拼错
    with caplog.at_level("INFO"):  # 留痕走 INFO（不是错误，是归类提示）
        result = scan_library(root)
    assert result.tracks[0].emotion == "default"
    assert "suspence" in caplog.text  # 留痕是人话，直接进日志/UI


# ---------- 文件名前缀兜底（平铺） ----------


def test_flat_filename_prefix_fallback(tmp_path: Path, fake_bpm: object) -> None:
    root = tmp_path / "bgm"
    _write_wav(root / "triumph_01.wav")
    _write_wav(root / "no_prefix_song.wav")
    by_name = {track.file.name: track.emotion for track in scan_library(root).tracks}
    assert by_name["triumph_01.wav"] == "triumph"
    assert by_name["no_prefix_song.wav"] == "default"


# ---------- manifest sidecar ----------


def test_manifest_attaches_license_fields(tmp_path: Path, fake_bpm: object) -> None:
    root = tmp_path / "bgm"
    _write_wav(root / "suspense" / "a.wav")
    (root / "bgm_manifest.json").write_text(
        json.dumps(
            {
                "suspense/a.wav": {
                    "license": "CC-BY 4.0",
                    "attribution": "Kevin MacLeod",
                    "source_url": "https://incompetech.com/x",
                }
            }
        ),
        encoding="utf-8",
    )
    (track,) = scan_library(root).tracks
    assert track.license == "CC-BY 4.0"
    assert track.attribution == "Kevin MacLeod"
    assert track.source_url == "https://incompetech.com/x"


def test_manifest_missing_or_broken_degrades_to_empty(
    tmp_path: Path, fake_bpm: object
) -> None:
    root = tmp_path / "bgm"
    _write_wav(root / "default" / "a.wav")
    (track,) = scan_library(root).tracks
    assert (track.license, track.attribution, track.source_url) == ("", "", "")
    (root / "bgm_manifest.json").write_text("{not json", encoding="utf-8")
    (track,) = scan_library(root).tracks  # 坏 JSON 降级空串，不 raise
    assert track.license == ""


# ---------- 降级纪律 ----------


def test_broken_file_skipped_with_reason(tmp_path: Path, fake_bpm: object) -> None:
    root = tmp_path / "bgm"
    _write_wav(root / "anger" / "good.wav")
    bad = root / "anger" / "bad.wav"
    bad.write_bytes(b"RIFF not really audio")
    result = scan_library(root)
    assert [track.file.name for track in result.tracks] == ["good.wav"]
    assert [path.name for path, _ in result.skipped] == ["bad.wav"]
    assert result.skipped[0][1]  # 跳过原因是人话，非空


def test_bpm_none_does_not_block_track(tmp_path: Path, fake_bpm: object) -> None:
    root = tmp_path / "bgm"
    _write_wav(root / "sadness" / "plain.wav")  # fake_bpm 对它返回 None（无 bpmNNN 记号）
    (track,) = scan_library(root).tracks
    assert track.bpm is None
    assert track.duration_s > 0


def test_measure_bpm_degrades_to_none_on_any_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """真 _measure_bpm：librosa 缺失/解码失败一律 None（增强不为崩溃买单）。"""
    wav = tmp_path / "x.wav"
    _write_wav(wav)

    import importlib

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("no librosa")

    monkeypatch.setattr(importlib, "import_module", _boom)
    assert library._measure_bpm(wav) is None


def test_missing_dir_is_empty_not_error(tmp_path: Path) -> None:
    result = scan_library(tmp_path / "does_not_exist")
    assert result.tracks == [] and result.skipped == []


def test_non_audio_files_ignored(tmp_path: Path, fake_bpm: object) -> None:
    root = tmp_path / "bgm"
    _write_wav(root / "default" / "a.wav")
    (root / "default" / "notes.txt").write_text("不是音频", encoding="utf-8")
    (track,) = scan_library(root).tracks
    assert track.file.name == "a.wav"


def test_duration_measured_by_ffprobe(tmp_path: Path, fake_bpm: object) -> None:
    root = tmp_path / "bgm"
    _write_wav(root / "default" / "two_sec.wav", seconds=2.0)
    (track,) = scan_library(root).tracks
    assert 1.9 <= track.duration_s <= 2.1  # 真测（ffprobe），不是文件名猜的


def test_scan_is_deterministic_order(tmp_path: Path, fake_bpm: object) -> None:
    root = tmp_path / "bgm"
    for name in ("b.wav", "a.wav"):
        _write_wav(root / "anger" / name)
    first = [track.file.name for track in scan_library(root).tracks]
    second = [track.file.name for track in scan_library(root).tracks]
    assert first == second == ["a.wav", "b.wav"]  # 目录序稳定


def test_bgm_track_is_frozen(tmp_path: Path, fake_bpm: object) -> None:
    root = tmp_path / "bgm"
    _write_wav(root / "default" / "a.wav")
    track = scan_library(root).tracks[0]
    assert isinstance(track, BgmTrack)
    with pytest.raises(Exception):  # noqa: B017, PT011 - frozen dataclass 拒绝一切写
        track.emotion = "anger"  # type: ignore[misc]
