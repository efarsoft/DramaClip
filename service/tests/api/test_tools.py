"""tools 命名空间：文案提取作业（异步跑通落产物）+ 长文 TTS + 结果查询。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import tools as tools_api
from dramaclip.engines.analysis.models import AsrSegment, OcrSegment


@pytest.fixture()
def context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    conn = sqlite3.connect(":memory:")
    store: dict[str, dict[str, Any]] = {}

    class _Store:
        """JobStore 的最小替身：形状对齐 tools.get_result 的消费面。"""

        def create(self, job_type: str, ref_id: str | None = None) -> str:
            job_id = f"j{len(store) + 1}"
            store[job_id] = {"status": "pending", "error": None, "type": job_type}
            return job_id

        def mark_running(self, job_id: str) -> None:
            store[job_id]["status"] = "running"

        def mark_completed(self, job_id: str) -> None:
            store[job_id]["status"] = "completed"

        def mark_failed(self, job_id: str, error: str) -> None:
            store[job_id]["status"] = "failed"
            store[job_id]["error"] = error

        def get(self, job_id: str) -> dict[str, Any] | None:
            return store.get(job_id)

    context = SimpleNamespace(
        conn=conn,
        data_dir=tmp_path,
        work_dir=tmp_path / "cache",
        settings={"asr.language": "zh", "tts.engine": "edge"},
        job_store=_Store(),
        analysis_runtime=SimpleNamespace(transcriber=lambda: None),
        cancel_events={},
        executor=SimpleNamespace(submit=lambda fn: fn()),
        notifier=SimpleNamespace(
            tracked=lambda job_id, fn, *a: (lambda: fn(*a)),
            progress=lambda job_id, percent, text: None,
            log=lambda level, message: None,
        ),
    )
    monkeypatch.setattr(tools_api, "_media_duration_s", lambda _p: 138.2)
    return context


def _seed_media(monkeypatch: pytest.MonkeyPatch, video: Path) -> None:
    monkeypatch.setattr(tools_api, "extract_audio", lambda v, w: Path(w).write_bytes(b"x"))
    monkeypatch.setattr(
        tools_api.subtitle_ocr, "extract_subtitles", lambda v, w, *, duration_s: (
            [
                OcrSegment(start=1.0, end=5.0, text="皇后变卖首饰"),
                OcrSegment(start=6.0, end=9.0, text="才凑出五千两"),
            ],
            None,
            None,
        )
    )


class _FakeTranscriber:
    def __init__(self, segments: list[AsrSegment]) -> None:
        self.segments = segments

    def transcribe(self, wav: Path, language: str = "zh", hotwords: str = "") -> list[AsrSegment]:
        return self.segments


def test_extract_job_runs_and_persists_artifacts(
    context: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "ep1.mp4"
    video.write_bytes(b"x")
    _seed_media(monkeypatch, video)
    asr = [AsrSegment(start=1.2, end=4.8, text="皇后变卖首饰，才凑出五千两")]
    monkeypatch.setattr(
        context.analysis_runtime, "transcriber", lambda: _FakeTranscriber(asr)
    )

    r = tools_api.extract_start(context, {"video_path": str(video)})
    job_id = r["job_id"]
    result = tools_api.get_result(context, {"job_id": job_id})
    assert result["status"] == "completed"
    payload = result["result"]
    assert payload is not None and payload["text"].startswith("皇后变卖首饰")
    assert (Path(payload["txt_path"])).is_file()
    assert "-->" in (Path(payload["srt_path"])).read_text(encoding="utf-8")


def test_extract_start_rejects_missing_video(context: SimpleNamespace) -> None:
    from dramaclip.transport.rpc import RpcDomainError

    with pytest.raises(RpcDomainError, match="媒体文件不存在"):
        tools_api.extract_start(context, {"video_path": "Z:/不存在.mp4"})


def test_tts_writes_into_tools_dir(
    context: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synthesized: dict[str, str] = {}

    def _fake_synthesize(engine, voice, text, models_dir, out_dir, key, *, api_key, model):
        out = Path(out_dir) / f"{key}.mp3"
        out.write_bytes(b"x")
        synthesized["voice"] = voice
        synthesized["engine"] = engine
        synthesized["model"] = model
        return out

    monkeypatch.setattr(tools_api, "_resolve_voice", lambda c, e, p, m: "zf_001")
    monkeypatch.setattr(tools_api, "_synthesize", _fake_synthesize)

    context.settings["tts.model"] = "cosyvoice-v3-flash"
    r = tools_api.tts(context, {"text": "整段文案合成"})
    assert Path(r["path"]).is_file()
    assert r["engine"] == "edge" and r["chars"] == 6
    assert synthesized["voice"] == "zf_001"
    # 云端长文同样要按业主选的模型出，不能让工厂默认值替人做主
    assert synthesized["model"] == "cosyvoice-v3-flash"


# ------------------------------------------------- P2：语音转文字 / 文案改写


def test_asr_start_runs_without_ocr(
    context: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """纯音频走纯 ASR（无 OCR）；融合无字幕佐证时按设计回落纯 ASR 段。"""
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"x")

    def _no_ocr(*_a: Any, **_k: Any) -> None:
        raise AssertionError("音频文件不应触发 OCR")

    monkeypatch.setattr(tools_api.subtitle_ocr, "extract_subtitles", _no_ocr)
    monkeypatch.setattr(tools_api, "extract_audio", lambda v, w: Path(w).write_bytes(b"x"))
    asr = [AsrSegment(start=0.5, end=4.0, text="这是录音里的一句话")]
    monkeypatch.setattr(
        context.analysis_runtime, "transcriber", lambda: _FakeTranscriber(asr)
    )

    r = tools_api.asr_start(context, {"media_path": str(audio)})
    result = tools_api.get_result(context, {"job_id": r["job_id"]})
    assert result["status"] == "completed"
    assert result["result"] is not None
    assert "这是录音里的一句话" in result["result"]["text"]


def test_asr_start_rejects_video_extensions(context: SimpleNamespace, tmp_path: Path) -> None:
    from dramaclip.transport.rpc import RpcDomainError

    video = tmp_path / "ep1.mp4"
    video.write_bytes(b"x")
    with pytest.raises(RpcDomainError, match="不是音频文件"):
        tools_api.asr_start(context, {"media_path": str(video)})


class _RewriteFakeLlm:
    def __init__(self, config: Any, timeout_s: float = 60.0) -> None:
        self.payload: dict[str, Any] = {"text": ""}
        self.user = ""

    def chat_json(self, system: str, user: str, temperature: float = 0.3) -> Any:
        self.user = user
        return {"text": "改写后的文案", "notes": None}


def test_rewrite_paraphrase_annotates_generic_notes(
    context: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """复述改写：LLM 正常产出；元叙述/违禁引导词进 notes 软标注。"""
    context.settings.update({
        "llm.base_url": "http://llm.test/v1",
        "llm.api_key": "sk-test",
        "llm.model": "test-model",
    })

    class _Llm(_RewriteFakeLlm):
        def chat_json(self, system: str, user: str, temperature: float = 0.3) -> Any:
            self.user = user
            return {"text": "改写后的稿子，记得关注点赞"}

    monkeypatch.setattr(
        "dramaclip.engines.semantic.llm_client.LlmClient", _Llm
    )
    r = tools_api.rewrite(context, {"text": "原稿", "style": "paraphrase"})
    assert r["text"] == "改写后的稿子，记得关注点赞"
    assert any("关注/点赞" in note for note in r["notes"])
    assert "原文复述" in r["style"] or r["style"] == "paraphrase"


def test_rewrite_card_style_injects_style_card(
    context: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """按文风卡重写：user 提示词注入 STYLE_CARD（单一真相源）。"""
    context.settings.update({
        "llm.base_url": "http://llm.test/v1",
        "llm.api_key": "sk-test",
        "llm.model": "test-model",
    })
    captured: dict[str, str] = {}

    class _Llm(_RewriteFakeLlm):
        def chat_json(self, system: str, user: str, temperature: float = 0.3) -> Any:
            captured["user"] = user
            captured["system"] = system
            return {"text": "按文风卡重写的稿子"}

    monkeypatch.setattr(
        "dramaclip.engines.semantic.llm_client.LlmClient", _Llm
    )
    r = tools_api.rewrite(context, {"text": "原稿", "style": "card"})
    assert r["style"] == "card"
    assert "【文风标杆" in captured["user"], "文风卡应注入 user 提示词"


def test_rewrite_requires_llm_config(context: SimpleNamespace) -> None:
    from dramaclip.engines.semantic.llm_client import LlmUnavailable

    with pytest.raises(LlmUnavailable, match="引擎"):
        tools_api.rewrite(context, {"text": "原稿"})
