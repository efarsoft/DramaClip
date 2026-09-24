"""selftest._build_asr 的分派与 run_asr 的空结果口径。

两处判据：① paraformer/sensevoice/faster_whisper 各自建对引擎，且**构建不触
funasr/ctranslate2**（懒加载纪律：依赖没装时连分派表都建不起来就坏了）；
② 空转写不发绿灯——随包样例是真人语音，引擎出空就是没跑通（2026-09-24 实测
paraformer 输出缺时间戳被解析整条丢弃，chars=0 却 ok=true，正是假绿）。
"""

from pathlib import Path

import pytest

from dramaclip.engines.analysis.transcriber import (
    FasterWhisperEngine,
    ParaformerEngine,
    SenseVoiceEngine,
)
from dramaclip.infra.model_manager import registry, selftest
from dramaclip.infra.model_manager.registry import ModelSpec


def _spec(engine: str) -> ModelSpec:
    for spec in registry.builtin_specs():
        if spec.engine == engine:
            return spec
    raise AssertionError(f"内置清单里没有 engine={engine} 的资产")


def test_build_asr_dispatches_to_the_right_engine(tmp_path: Path) -> None:
    cases = [
        ("paraformer", ParaformerEngine),
        ("sensevoice", SenseVoiceEngine),
        ("faster_whisper", FasterWhisperEngine),
    ]
    for engine, cls in cases:
        built = selftest._build_asr(tmp_path, _spec(engine), "cpu", "auto")
        assert isinstance(built, cls), f"{engine} 该建 {cls.__name__}"


def test_build_asr_unknown_engine_says_so(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="没有能力层自检实现"):
        selftest._build_asr(tmp_path, _spec("kokoro"), "cpu", "auto")


class _MuteAsr:
    """加载成功但一个不出：正是 paraformer 缺时间戳时段的真实病灶。"""

    name = "paraformer"

    def transcribe(self, wav_path: Path, language: str = "zh", *, hotwords: str = "") -> list:  # type: ignore[type-arg]
        return []


def test_run_asr_empty_transcript_is_not_green(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(selftest, "_build_asr", lambda *_a, **_k: _MuteAsr())
    result = selftest.run_asr(tmp_path, _spec("paraformer"))
    assert result["ok"] is False
    assert "转写结果为空" in str(result["error"])
