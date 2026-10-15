"""云端引擎（P1）：Key 缺失的构造门 + 桩 SDK 的合成/解析链。"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.analysis.transcriber import DashscopeCloudAsrEngine
from dramaclip.engines.tts.engines.dashscope import DashscopeCosyVoiceEngine


def _write_wav(path: Path, seconds: float = 0.5, rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * int(rate * seconds))


def test_dashscope_asr_requires_api_key(tmp_path: Path) -> None:
    engine = DashscopeCloudAsrEngine(api_key="  ")
    with pytest.raises(ValueError, match="asr.api_key"):
        engine.transcribe(tmp_path / "ep.wav")


def test_dashscope_tts_requires_api_key() -> None:
    with pytest.raises(ValueError, match="tts.api_key"):
        DashscopeCosyVoiceEngine(api_key="")


def test_dashscope_tts_synthesizes_wav_via_stubbed_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """桩 SDK：call 返回字节 → 落 .wav；空音色回落引擎默认。"""
    captured: dict[str, str] = {}

    class _FakeFormat:
        WAV_22050HZ_MONO_16BIT = "wav-22050"

    class _FakeSynthesizer:
        def __init__(self, *, model: str, voice: str, format: str) -> None:  # noqa: A002
            captured["model"] = model
            captured["voice"] = voice
            captured["format"] = str(format)

        def call(self, text: str) -> bytes:
            captured["text"] = text
            return b"RIFF fake audio"

    monkeypatch.setattr(
        "dashscope.audio.tts_v2.SpeechSynthesizer", _FakeSynthesizer, raising=False
    )
    monkeypatch.setattr(
        "dashscope.audio.tts_v2.AudioFormat", _FakeFormat, raising=False
    )

    engine = DashscopeCosyVoiceEngine(api_key="sk-test")
    out = engine.synthesize("第一句台词", "", tmp_path / "seg-1.mp3")
    assert out == tmp_path / "seg-1.wav" and out.read_bytes().startswith(b"RIFF")
    assert captured == {
        "model": "cosyvoice-v2",
        "voice": "longxiaochun_v2",
        "format": "wav-22050",
        "text": "第一句台词",
    }


def _stub_sync_asr(
    monkeypatch: pytest.MonkeyPatch,
    captured: dict[str, Any],
    per_clip: list[list[dict[str, Any]]],
) -> None:
    """桩切片同步链：固定两片、逐片返回句表；每次调用的参数收进 captured。"""
    from dramaclip.engines.analysis import pause_split
    from dramaclip.engines.analysis import transcriber as mod

    clips = [pause_split.Clip(0.0, 2.0), pause_split.Clip(2.0, 4.0)]
    monkeypatch.setattr(mod.pause_split, "speech_clips", lambda _p, **_k: clips)
    monkeypatch.setattr(
        mod.pause_split,
        "split_wav",
        lambda _wav, clip_list, out_dir: [
            (clip, out_dir / f"clip-{index}.wav")
            for index, clip in enumerate(clip_list)
        ],
    )

    class _Resp:
        status_code = 200
        code = ""
        message = ""

        def __init__(self, sentences: list[dict[str, Any]]) -> None:
            self.output: dict[str, Any] = {"sentences": sentences}

    def _call(**kwargs: Any) -> _Resp:
        calls = captured.setdefault("calls", [])
        calls.append(kwargs)
        index = min(len(calls) - 1, len(per_clip) - 1)
        return _Resp(per_clip[index])

    monkeypatch.setattr(
        "dashscope.MultiModalConversation",
        type("MultiModalConversation", (), {"call": staticmethod(_call)}),
    )


def test_dashscope_asr_chunks_offsets_and_call_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """逐片同步调用：片起点偏移锚定整集时间轴；参数带 format/sample_rate/分离开关。"""
    captured: dict[str, Any] = {}
    _stub_sync_asr(
        monkeypatch,
        captured,
        [
            [
                {
                    "begin_time": 100,
                    "end_time": 1500,
                    "text": "陛下大事不好",
                    "words": [
                        {"begin_time": 100, "end_time": 300, "text": "陛", "speaker_id": 0},
                        {"begin_time": 300, "end_time": 500, "text": " ", "speaker_id": 0},
                        {"begin_time": 500, "end_time": 1500, "text": "下", "speaker_id": 0},
                    ],
                }
            ],
            [
                {
                    "begin_time": 200,
                    "end_time": 1200,
                    "text": "何事惊慌",
                    "words": [
                        {"begin_time": 200, "end_time": 1200, "text": "何事惊慌", "speaker_id": 1}
                    ],
                }
            ],
        ],
    )
    wav = tmp_path / "ep.wav"
    _write_wav(wav)
    segments = DashscopeCloudAsrEngine(api_key="sk-test").transcribe(wav)
    assert [(s.start, s.end, s.text) for s in segments] == [
        (0.1, 1.5, "陛下大事不好"),
        (2.2, 3.2, "何事惊慌"),
    ]
    # 空白占位词过滤；字级时间戳同样偏移
    assert [w.word for w in segments[0].words] == ["陛", "下"]
    assert segments[0].words[1].start == 0.5 and segments[0].words[1].end == 1.5
    # 调用形状：本地路径 file:// 交 SDK 自动上传；格式/采样率/分离开关如实传
    assert len(captured["calls"]) == 2
    first = captured["calls"][0]
    assert first["model"] == "qwen-audio-3.1-asr-flash"
    assert first["format"] == "wav" and first["sample_rate"] == "16000"
    assert first["speaker_diarization_enabled"] is True
    assert first["messages"][0]["content"][0]["audio"].startswith("file://")


def test_dashscope_asr_speaker_labels_from_word_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """说话人取字级 speaker_id 按出场顺序映射角色A/B…（句级聚合字段不采信）。"""
    captured: dict[str, Any] = {}
    _stub_sync_asr(
        monkeypatch,
        captured,
        [
            [
                {
                    # 句级 speaker_id=9 是聚合对象（不可信）；字级 0 才是真值
                    "begin_time": 0,
                    "end_time": 1000,
                    "text": "一句",
                    "speaker_id": 9,
                    "words": [
                        {"begin_time": 0, "end_time": 500, "text": "一", "speaker_id": 0},
                        {"begin_time": 500, "end_time": 1000, "text": "句", "speaker_id": 0},
                    ],
                },
                {
                    "begin_time": 1200,
                    "end_time": 2000,
                    "text": "二句",
                    "speaker_id": 9,
                    "words": [
                        {"begin_time": 1200, "end_time": 2000, "text": "二句", "speaker_id": 3}
                    ],
                },
            ],
            [],  # 第二片无语音 → 空
        ],
    )
    wav = tmp_path / "ep.wav"
    _write_wav(wav)
    segments = DashscopeCloudAsrEngine(api_key="sk-test").transcribe(wav)
    assert [s.speaker for s in segments] == ["角色A", "角色B"]


def test_dashscope_asr_diarization_off_and_wordless_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """diarization 关闭不传分离开关；无字级明细的模型整句一个词、说话人为 None。"""
    captured: dict[str, Any] = {}
    _stub_sync_asr(
        monkeypatch,
        captured,
        [[{"begin_time": 0, "end_time": 1000, "text": "整句无字级"}]],
    )
    wav = tmp_path / "ep.wav"
    _write_wav(wav)
    engine = DashscopeCloudAsrEngine(api_key="sk-test", diarization=False)
    segments = engine.transcribe(wav)
    assert "speaker_diarization_enabled" not in captured["calls"][0]
    assert segments[0].speaker is None
    assert segments[0].words[0].word == "整句无字级"
    assert segments[0].words[0].start == 0.0 and segments[0].words[0].end == 1.0
