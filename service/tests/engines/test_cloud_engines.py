"""云端引擎（P1）：Key 缺失的构造门 + 桩 SDK 的合成/解析链。"""

from __future__ import annotations

import json
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


class _BytesResp:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def __enter__(self) -> _BytesResp:
        return self

    def __exit__(self, *_a: object) -> None:
        return None

    def read(self) -> bytes:
        return self._data


def _stub_tts_http(
    monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any], audio: bytes
) -> None:
    """桩 HTTP 链：合成端点返回音频 URL → 下载字节；请求载荷收进 captured。"""

    def _fake_urlopen(request: Any, timeout: float) -> _BytesResp:
        url = str(getattr(request, "full_url", request))
        if "SpeechSynthesizer" in url:
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["auth"] = request.headers.get("Authorization")
            body = {"output": {"audio": {"url": "http://audio-result/x.wav"}}}
            return _BytesResp(json.dumps(body).encode("utf-8"))
        return _BytesResp(audio)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)


def test_dashscope_tts_synthesizes_wav_via_http_stub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """桩 HTTP：POST 合成端点 → 音频 URL → 下载落盘；载荷形状与鉴权头如实传。"""
    captured: dict[str, Any] = {}
    _stub_tts_http(monkeypatch, captured, b"RIFF fake audio")

    engine = DashscopeCosyVoiceEngine(api_key="sk-test")
    out = engine.synthesize("第一句台词", "longwan_v2", tmp_path / "seg-1.mp3")
    assert out == tmp_path / "seg-1.wav" and out.read_bytes() == b"RIFF fake audio"
    assert captured["auth"] == "Bearer sk-test"
    assert captured["payload"] == {
        "model": "cosyvoice-v2",
        "input": {
            "text": "第一句台词",
            "voice": "longwan_v2",
            "format": "wav",
            "sample_rate": 22050,
        },
    }


def test_dashscope_tts_default_voice_follows_model_gen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """三族音色体系互不相通：空音色按模型代际回落各自官方默认。"""
    cases = {
        "cosyvoice-v2": "longxiaochun_v2",
        "cosyvoice-v3-flash": "longanyang",
        "qwen-audio-3.0-tts-flash": "longanhuan_v3.6",
    }
    for model, expected_voice in cases.items():
        captured: dict[str, Any] = {}
        _stub_tts_http(monkeypatch, captured, b"RIFF")
        DashscopeCosyVoiceEngine(api_key="sk-test", model=model).synthesize(
            "台词", "", tmp_path / "t.wav"
        )
        assert captured["payload"]["input"]["voice"] == expected_voice, model


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


def test_dashscope_asr_chunk_fallback_is_traced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """停顿分析量不出来 → 整条一片兜底，但这次退回要在日志里留痕。

    与本地 paraformer 同一条判据：退回整条是**改变观众所见字幕**的降级，
    静默退回等于「界面说切了、产物没切」。
    """
    from dramaclip.engines.analysis import pause_split

    def unavailable(_wav: Path, **_kw: Any) -> list[Any]:
        raise pause_split.PauseAnalysisUnavailable("音频过短，无法分析")

    monkeypatch.setattr(pause_split, "speech_clips", unavailable)
    wav = tmp_path / "ep.wav"
    _write_wav(wav, seconds=2.0)

    chunks = DashscopeCloudAsrEngine(api_key="sk-test")._chunks(wav)

    assert [(c.start, c.end) for c in chunks] == [(0.0, 2.0)]
    assert "停顿切分" in caplog.text


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
