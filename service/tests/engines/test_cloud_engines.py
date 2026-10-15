"""云端引擎（P1）：Key 缺失的构造门 + 桩 SDK 的合成/解析链。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
    # 无字级时间戳的句：整句一个词，时间不丢
    assert segments[1].words[0].word == "何事惊慌。"
    assert segments[1].words[0].start == 2.0 and segments[1].words[0].end == 3.0


def _stub_asr_chain(
    monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any], transcript: dict[str, Any]
) -> None:
    """桩完整云端转写链：上传桥恒返回假 URL，提交参数收进 captured，转写 JSON 固定。"""
    import dashscope.audio.asr as asr_mod

    from dramaclip.engines.analysis import transcriber as mod

    class _Resp:
        def __init__(self, output: dict[str, Any]) -> None:
            self.status_code = 200
            self.output = output
            self.message = ""

    def _submit(**kwargs: Any) -> _Resp:
        captured.update(kwargs)
        return _Resp({"task_id": "t1"})

    monkeypatch.setattr(
        "dashscope.utils.oss_utils.check_and_upload_local",
        lambda **_k: (True, "https://oss.tmp/a.wav", None),
    )
    monkeypatch.setattr(asr_mod.Transcription, "call", _submit)
    monkeypatch.setattr(
        asr_mod.Transcription,
        "fetch",
        lambda **_k: _Resp(
            {
                "task_status": "SUCCEEDED",
                "results": [{"transcription_url": "http://x/t"}],
            }
        ),
    )

    class _HttpResp:
        def __enter__(self) -> _HttpResp:
            return self

        def __exit__(self, *_a: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(transcript).encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda _r, timeout: _HttpResp())
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)


def test_dashscope_asr_uploads_local_before_submit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """本地 wav 先过 SDK 临时上传桥换公网 URL；提交参数带说话人分离开关与语种提示。"""
    captured: dict[str, Any] = {}
    _stub_asr_chain(monkeypatch, captured, {"transcripts": []})
    wav = tmp_path / "ep.wav"
    wav.write_bytes(b"RIFF")
    segments = DashscopeParaformerEngine(api_key="sk-test").transcribe(wav)
    assert segments == []
    assert captured["file_urls"] == ["https://oss.tmp/a.wav"]
    assert captured["diarization_enabled"] is True
    assert captured["language_hints"] == ["zh"]


def test_dashscope_asr_language_hints_only_for_paraformer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """fun-asr / qwen 系不接受 language_hints——非 paraformer 模型不传该参数。"""
    captured: dict[str, Any] = {}
    _stub_asr_chain(monkeypatch, captured, {"transcripts": []})
    DashscopeParaformerEngine(api_key="sk-test", model="fun-asr").transcribe(
        tmp_path / "ep.wav"
    )
    assert "language_hints" not in captured
    assert captured["diarization_enabled"] is True


def test_dashscope_asr_speaker_labels_follow_local_convention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """云端 speaker_id → 角色A/B…（按出场顺序，与本地聚类标签同格式）；缺失为 None。"""
    transcript = {
        "transcripts": [
            {
                "sentences": [
                    {"begin_time": 0, "end_time": 1000, "text": "一", "speaker_id": 7},
                    {"begin_time": 1000, "end_time": 2000, "text": "二", "speaker_id": 3},
                    {"begin_time": 2000, "end_time": 3000, "text": "三", "speaker_id": 7},
                    {"begin_time": 3000, "end_time": 4000, "text": "四"},
                ]
            }
        ]
    }
    _stub_asr_chain(monkeypatch, {}, transcript)
    segments = DashscopeParaformerEngine(api_key="sk-test").transcribe(tmp_path / "ep.wav")
    assert [s.speaker for s in segments] == ["角色A", "角色B", "角色A", None]
