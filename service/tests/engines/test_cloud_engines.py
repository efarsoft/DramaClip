"""云端引擎（P1 + 火山）：Key 缺失的构造门 + 桩 SDK / 桩 HTTP 的合成/解析链。"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.analysis.transcriber import (
    DashscopeParaformerEngine,
    VolcFileAsrEngine,
)
from dramaclip.engines.tts.engines.dashscope import DashscopeCosyVoiceEngine
from dramaclip.engines.tts.engines.volc import VolcTtsEngine


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


# ── 火山引擎：ASR 极速版（一次请求，状态码在响应头）+ TTS V1（Bearer;token） ──────


class _StubHttpResponse:
    """桩 urlopen 返回体：headers 为普通 dict（代码侧只调 .items()）。"""

    def __init__(self, headers: dict[str, str], body: dict[str, Any]) -> None:
        self.headers = headers
        self._body = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _StubHttpResponse:
        return self

    def __exit__(self, *_a: object) -> None:
        return None


def _stub_urlopen(
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str],
    body: dict[str, Any],
    captured: dict[str, Any],
) -> None:
    def _fake(request: Any, timeout: float) -> _StubHttpResponse:
        captured["url"] = request.full_url
        captured["req_headers"] = {
            k.lower(): v for k, v in request.header_items()
        }
        captured["req_body"] = json.loads(request.data.decode("utf-8"))
        return _StubHttpResponse(headers, body)

    monkeypatch.setattr("urllib.request.urlopen", _fake)


def test_volc_asr_flash_parses_utterances(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """极速版：头 X-Api-Status-Code=20000000 判成，体 utterances（毫秒）→ AsrSegment。"""
    wav = tmp_path / "ep.wav"
    wav.write_bytes(b"RIFF fake wav")
    captured: dict[str, Any] = {}
    _stub_urlopen(
        monkeypatch,
        {"X-Api-Status-Code": "20000000", "X-Api-Message": "success"},
        {
            "result": {
                "utterances": [
                    {
                        "text": "陛下，大事不好。",
                        "start_time": 100,
                        "end_time": 1500,
                        "words": [
                            {"text": "陛", "start_time": 100, "end_time": 300},
                            {"text": "上", "start_time": 300, "end_time": 500},
                        ],
                    },
                    {"text": "何事惊慌。", "start_time": 2000, "end_time": 3000, "words": []},
                ]
            }
        },
        captured,
    )
    engine = VolcFileAsrEngine(api_key="app-123:tok")
    segments = engine.transcribe(wav)
    assert [(s.start, s.end, s.text) for s in segments] == [
        (0.1, 1.5, "陛下，大事不好。"),
        (2.0, 3.0, "何事惊慌。"),
    ]
    assert segments[0].words[1].start == pytest.approx(0.3)
    # 无 words 的句整句一个词，时间不丢
    assert segments[1].words[0].word == "何事惊慌。"
    assert segments[1].words[0].start == 2.0 and segments[1].words[0].end == 3.0
    assert captured["url"].endswith("/api/v3/auc/bigmodel/recognize/flash")
    rh = captured["req_headers"]
    assert rh["x-api-app-key"] == "app-123"
    assert rh["x-api-access-key"] == "tok"
    assert rh["x-api-resource-id"] == "volc.bigasr.auc_turbo"
    assert rh["x-api-sequence"] == "-1"
    assert captured["req_body"]["audio"]["format"] == "wav"
    assert captured["req_body"]["request"]["show_utterances"] is True


def test_volc_asr_new_console_single_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """新版控制台单凭证：不含冒号的 Key 发 X-Api-Key 单头。"""
    wav = tmp_path / "ep.wav"
    wav.write_bytes(b"RIFF")
    captured: dict[str, Any] = {}
    _stub_urlopen(
        monkeypatch,
        {"X-Api-Status-Code": "20000000"},
        {"result": {"utterances": []}},
        captured,
    )
    segments = VolcFileAsrEngine(api_key="volc-single-key").transcribe(wav)
    assert segments == []
    rh = captured["req_headers"]
    assert rh["x-api-key"] == "volc-single-key"
    assert "x-api-app-key" not in rh


def test_volc_asr_silence_is_empty_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """20000003=静音音频：链路已通、识别为空段——连通测试的静音 wav 就靠这条路。"""
    wav = tmp_path / "ep.wav"
    wav.write_bytes(b"RIFF")
    _stub_urlopen(
        monkeypatch,
        {"X-Api-Status-Code": "20000003", "X-Api-Message": "silent audio"},
        {},
        {},
    )
    assert VolcFileAsrEngine(api_key="a:b").transcribe(wav) == []


def test_volc_asr_error_status_surfaces_header_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wav = tmp_path / "ep.wav"
    wav.write_bytes(b"RIFF")
    _stub_urlopen(
        monkeypatch,
        {
            "X-Api-Status-Code": "45000001",
            "X-Api-Message": "Invalid Parameter",
            "X-Tt-Logid": "log-9",
        },
        {},
        {},
    )
    with pytest.raises(RuntimeError, match="45000001.*Invalid Parameter.*log-9"):
        VolcFileAsrEngine(api_key="a:b").transcribe(wav)


def test_volc_asr_rejects_oversized_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wav = tmp_path / "ep.wav"
    wav.write_bytes(b"RIFF fake")
    monkeypatch.setattr(VolcFileAsrEngine, "_MAX_AUDIO_BYTES", 8)
    with pytest.raises(ValueError, match="100MB"):
        VolcFileAsrEngine(api_key="a:b").transcribe(wav)


def test_volc_asr_requires_credentials(tmp_path: Path) -> None:
    wav = tmp_path / "ep.wav"
    wav.write_bytes(b"RIFF")
    with pytest.raises(ValueError, match="asr.api_key"):
        VolcFileAsrEngine(api_key="  ").transcribe(wav)


def test_volc_tts_synthesizes_wav(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """V1 非流式：Bearer;token 分号鉴权 + code 3000 → base64 wav 落盘。"""
    captured: dict[str, Any] = {}
    _stub_urlopen(
        monkeypatch,
        {},
        {
            "code": 3000,
            "message": "success",
            "data": base64.b64encode(b"RIFF fake audio").decode("ascii"),
        },
        captured,
    )
    engine = VolcTtsEngine(api_key="app-9:tok-9")
    out = engine.synthesize("第一句台词", "", tmp_path / "seg-1.mp3")
    assert out == tmp_path / "seg-1.wav" and out.read_bytes().startswith(b"RIFF")
    assert captured["url"] == "https://openspeech.bytedance.com/api/v1/tts"
    rh = captured["req_headers"]
    assert rh["authorization"] == "Bearer;tok-9"
    assert captured["req_body"]["app"] == {
        "appid": "app-9",
        "token": "access_token",
        "cluster": "volcano_tts",
    }
    assert captured["req_body"]["audio"] == {
        "voice_type": "zh_female_cancan_mars_bigtts",
        "encoding": "wav",
    }
    assert captured["req_body"]["request"]["operation"] == "query"


def test_volc_tts_error_code_surfaces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_urlopen(monkeypatch, {}, {"code": 3050, "message": "voice not exist", "data": ""}, {})
    with pytest.raises(RuntimeError, match="3050.*voice not exist"):
        VolcTtsEngine(api_key="a:b").synthesize("你好", "bad_voice", tmp_path / "x.wav")


def test_volc_tts_requires_dual_credentials(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="appid:token"):
        VolcTtsEngine(api_key="solo-key").synthesize("你好", "", tmp_path / "x.wav")


def test_volc_tts_rejects_oversized_text(tmp_path: Path) -> None:
    engine = VolcTtsEngine(api_key="a:b")
    with pytest.raises(ValueError, match="1024"):
        engine.synthesize("字" * 400, "", tmp_path / "x.wav")
