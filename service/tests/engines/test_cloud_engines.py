"""云端引擎（P1）：Key 缺失的构造门 + 桩 SDK 的合成/解析链。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dramaclip.engines.analysis.transcriber import DashscopeParaformerEngine
from dramaclip.engines.tts.engines.dashscope import DashscopeCosyVoiceEngine


def test_dashscope_asr_requires_api_key(tmp_path: Path) -> None:
    engine = DashscopeParaformerEngine(api_key="  ")
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


def test_dashscope_asr_parses_sentences(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """桩轮询链：提交→SUCCEEDED→转写 JSON 两个句子 → AsrSegment（字级 words）。"""
    import dashscope.audio.asr as asr_mod

    from dramaclip.engines.analysis import transcriber as mod

    class _Resp:
        def __init__(self, status_code: int, output: dict | None = None, message: str = "") -> None:
            self.status_code = status_code
            self.output = output or {}
            self.message = message

    monkeypatch.setattr(asr_mod.Transcription, "call", lambda **_k: _Resp(200, {"task_id": "t1"}))
    monkeypatch.setattr(
        asr_mod.Transcription,
        "fetch",
        lambda **_k: _Resp(
            200,
            {
                "task_status": "SUCCEEDED",
                "results": [{"transcription_url": "http://x/transcript"}],
            },
        ),
    )
    payload = {
        "transcripts": [
            {
                "sentences": [
                    {
                        "begin_time": 100,
                        "end_time": 1500,
                        "text": "陛下，大事不好。",
                        "words": [
                            {"begin_time": 100, "end_time": 300, "text": "陛"},
                            {"begin_time": 300, "end_time": 500, "text": "上"},
                        ],
                    },
                    {"begin_time": 2000, "end_time": 3000, "text": "何事惊慌。", "words": []},
                ]
            }
        ]
    }

    class _HttpResp:
        def __enter__(self) -> _HttpResp:
            return self

        def __exit__(self, *_a: object) -> None:
            return None

        def read(self) -> bytes:
            import json

            return json.dumps(payload).encode("utf-8")

    def _fake_urlopen(request: object, timeout: float) -> _HttpResp:
        return _HttpResp()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    engine = DashscopeParaformerEngine(api_key="sk-test")
    segments = engine.transcribe(tmp_path / "ep.wav")
    assert [(s.start, s.end, s.text) for s in segments] == [
        (0.1, 1.5, "陛下，大事不好。"),
        (2.0, 3.0, "何事惊慌。"),
    ]
    assert segments[0].words[0].word == "陛" and segments[0].speaker is None
