"""ParaformerEngine 契约：funasr 替身钉行为——generate 参数、字间隙聚句、配对兜底。

不需要真模型：funasr 进 sys.modules 假货（与 test_long_text_synth 的 edge_tts 同形），
只钉「代码怎么调 funasr」与「funasr 输出怎么变成 AsrSegment」这两个我们写的东西。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.analysis.transcriber import (
    ParaformerEngine,
    _pair,
    _parse_paraformer,
)

_REPO_ID = "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"


class _FakeAutoModel:
    instances: list[_FakeAutoModel] = []

    def __init__(self, model: str, **_kw: Any) -> None:
        self.model_arg = model
        self.generate_calls: list[dict[str, Any]] = []
        self.reply: list[dict[str, Any]] = []
        _FakeAutoModel.instances.append(self)

    def generate(self, **kw: Any) -> list[dict[str, Any]]:
        self.generate_calls.append(kw)
        return self.reply


@pytest.fixture
def fake_funasr(monkeypatch: pytest.MonkeyPatch) -> type[_FakeAutoModel]:
    _FakeAutoModel.instances = []
    monkeypatch.setitem(sys.modules, "funasr", type("m", (), {"AutoModel": _FakeAutoModel}))
    return _FakeAutoModel


def test_local_dir_preferred_then_repo_id(
    tmp_path: Path, fake_funasr: type[_FakeAutoModel]
) -> None:
    """落盘目录在场用目录（managed 路径），不在场回仓库 id（funasr 自缓存）。"""
    placed = tmp_path / "asr" / "paraformer"
    placed.mkdir(parents=True)
    ParaformerEngine(models_dir=tmp_path)._ensure_model()
    assert fake_funasr.instances[0].model_arg == str(placed)
    ParaformerEngine(models_dir=tmp_path / "nope")._ensure_model()
    assert fake_funasr.instances[1].model_arg == _REPO_ID


def test_generate_gets_batch_and_hotwords(
    tmp_path: Path, fake_funasr: type[_FakeAutoModel]
) -> None:
    engine = ParaformerEngine(models_dir=tmp_path / "nope")
    engine._ensure_model().reply = []
    engine.transcribe(Path("a.wav"), hotwords="废柴 反转")

    call = fake_funasr.instances[0].generate_calls[0]
    assert call["input"] == "a.wav"
    assert call["batch_size_s"] == 300, "整集 wav 长音频动态批"
    assert call["hotword"] == "废柴 反转", "热词走 paraformer 原生槽位"
    engine.transcribe(Path("a.wav"))
    assert fake_funasr.instances[0].generate_calls[1]["hotword"] is None, "无热词不传空串"


def test_char_gap_splits_sentences(tmp_path: Path, fake_funasr: type[_FakeAutoModel]) -> None:
    """字间隙 >0.6s 断句：两句话各自成段、时间取实测首末字、words 带字级跨度。"""
    engine = ParaformerEngine(models_dir=tmp_path / "nope")
    # 「你好」0.0-0.5s，「再见」1.5-2.2s：中间 1.0s 间隙断句
    engine._ensure_model().reply = [{
        "text": "你好再见",
        "timestamp": [[0, 300], [300, 500], [1500, 1900], [1900, 2200]],
    }]

    segments = engine.transcribe(Path("a.wav"))

    assert [s.text for s in segments] == ["你好", "再见"]
    assert (segments[0].start, segments[0].end) == (0.0, 0.5)
    assert (segments[1].start, segments[1].end) == (1.5, 2.2)
    assert [w.word for w in segments[0].words] == ["你", "好"]
    assert segments[0].words[0].probability == 1.0


def test_timestamp_shortfall_keeps_all_text(
    tmp_path: Path, fake_funasr: type[_FakeAutoModel]
) -> None:
    """时间戳比字少：可配对前缀照走，剩余文本并入末跨度——文本一个不丢。"""
    engine = ParaformerEngine(models_dir=tmp_path / "nope")
    engine._ensure_model().reply = [{
        "text": "三个字",
        "timestamp": [[0, 300], [300, 600]],
    }]

    segments = engine.transcribe(Path("a.wav"))

    assert len(segments) == 1
    assert segments[0].text == "三个字"
    assert (segments[0].start, segments[0].end) == (0.0, 0.6)


def test_bad_shapes_yield_empty_not_crash() -> None:
    assert _parse_paraformer([{"text": "", "timestamp": [[0, 1]]}], 0.6) == []
    assert _parse_paraformer([{"text": "字", "timestamp": []}], 0.6) == []
    assert _parse_paraformer([], 0.6) == []


def test_pair_short_timestamps_tail_merged() -> None:
    assert _pair(["a", "b"], [[0.0, 1.0]]) == [("ab", (0.0, 1.0))]
    assert _pair(["a"], [[0.0, 1.0], [2.0, 3.0]]) == [("a", (0.0, 1.0))]
    assert _pair([], [[0.0, 1.0]]) == []
