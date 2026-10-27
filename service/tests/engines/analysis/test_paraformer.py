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

    def __init__(self, model: str, **kw: Any) -> None:
        self.model_arg = model
        self.init_kwargs = kw
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


def test_one_bad_clip_skipped_not_fatal(
    tmp_path: Path, fake_funasr: type[_FakeAutoModel], monkeypatch: pytest.MonkeyPatch
) -> None:
    """切片级隔离（真机 2026-10-27 大明第8集立案）：funasr 上游 token/时间戳
    不齐时 IndexError（sentence_postprocess `time_stamp[i][0]`），一个坏切片
    跳过留痕、其余照常出词；全部失败才诚实失败。"""
    from dramaclip.engines.analysis import pause_split

    engine = ParaformerEngine(models_dir=tmp_path / "nope")
    model = engine._ensure_model()
    calls = {"n": 0}

    def generate(**kw: Any) -> list[dict[str, Any]]:
        calls["n"] += 1
        if calls["n"] == 2:  # 第二个切片命中上游 bug
            raise IndexError("list index out of range")
        return [{"text": "你好", "timestamp": [[0, 500]]}]

    model.generate = generate
    clips = [
        pause_split.Clip(start=0.0, end=5.0),
        pause_split.Clip(start=5.0, end=10.0),
    ]
    monkeypatch.setattr(pause_split, "speech_clips", lambda *_a, **_k: clips)
    monkeypatch.setattr(pause_split, "fill_degenerate", lambda *_a, **_k: None)
    monkeypatch.setattr(
        pause_split,
        "split_wav",
        lambda wav, cl, work: [
            (c, Path(f"{wav.stem}-clip{i}.wav")) for i, c in enumerate(cl, 1)
        ],
    )

    segments = engine.transcribe(Path("a.wav"))

    assert calls["n"] == 2, "坏切片之后的切片仍被转写"
    assert [(s.start, s.end, s.text) for s in segments] == [(0.0, 0.5, "你好")]

    # 全部切片都失败：最后的错误如实出去，不静默出空转写
    def always_boom(**kw: Any) -> list[dict[str, Any]]:
        raise IndexError("list index out of range")

    model.generate = always_boom
    with pytest.raises(RuntimeError, match="全部 2 个切片转写失败"):
        engine.transcribe(Path("a.wav"))


def test_unexpected_pause_analysis_error_propagates(
    tmp_path: Path,
    fake_funasr: type[_FakeAutoModel],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """停顿分析里的意外 ValueError 必须抛出，不许被当成「素材不可用」退回整条直喂。

    `strict=True` 的 zip 必抛 ValueError 被吞了这么久，根因就是这层宽判据：
    真失败与「这段素材量不出来」共用一个异常类型，于是功能静默关闭、日志无痕。
    """
    from dramaclip.engines.analysis import pause_split

    def boom(_wav: Path, **_kw: Any) -> list[Any]:
        raise ValueError("不该被吞的编程错误")

    monkeypatch.setattr(pause_split, "speech_clips", boom)
    engine = ParaformerEngine(models_dir=tmp_path / "nope")

    with pytest.raises(ValueError, match="不该被吞的编程错误"):
        engine.transcribe(Path("a.wav"))


def test_pause_analysis_unavailable_falls_back_and_logs(
    tmp_path: Path,
    fake_funasr: type[_FakeAutoModel],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """如实的量不出来（格式不合/过短）→ 退回整条直喂，但必须留痕。"""
    from dramaclip.engines.analysis import pause_split

    def unavailable(_wav: Path, **_kw: Any) -> list[Any]:
        raise pause_split.PauseAnalysisUnavailable("音频过短，无法分析")

    monkeypatch.setattr(pause_split, "speech_clips", unavailable)
    engine = ParaformerEngine(models_dir=tmp_path / "nope")

    assert engine.transcribe(Path("a.wav")) == []
    assert "停顿切分" in caplog.text, "退回整条是一次降级，翻日志要看得见"


def test_bad_shapes_yield_empty_not_crash() -> None:
    assert _parse_paraformer([{"text": "", "timestamp": [[0, 1]]}], 0.6) == []
    assert _parse_paraformer([{"text": "字", "timestamp": []}], 0.6) == []
    assert _parse_paraformer([], 0.6) == []


def test_pair_short_timestamps_tail_merged() -> None:
    assert _pair(["a", "b"], [[0.0, 1.0]]) == [("ab", (0.0, 1.0))]
    assert _pair(["a"], [[0.0, 1.0], [2.0, 3.0]]) == [("a", (0.0, 1.0))]
    assert _pair([], [[0.0, 1.0]]) == []


# ---- 说话人分离：AutoModel 装配、人数指定、speaker 归属 ----


def test_diarization_wires_vad_and_spk_models(
    tmp_path: Path, fake_funasr: type[_FakeAutoModel]
) -> None:
    """分离开启：vad/spk 模型按落盘目录传（managed 路径），spk_mode 显式 vad_segment。"""
    vad = tmp_path / "asr" / "fsmn-vad"
    spk = tmp_path / "asr" / "campplus"
    vad.mkdir(parents=True)
    spk.mkdir(parents=True)
    engine = ParaformerEngine(models_dir=tmp_path, vad_model_dir=vad, spk_model_dir=spk)
    engine._ensure_model()

    assert engine.diarization
    kwargs = fake_funasr.instances[0].init_kwargs
    assert kwargs["vad_model"] == str(vad)
    assert kwargs["spk_model"] == str(spk)
    assert kwargs["spk_mode"] == "vad_segment", "标点模型不挂，显式 vad_segment 免库内假警报"


def test_diarization_kwargs_fall_back_to_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """模型目录不在场：funasr 别名兜底（库自己拉 cam++/fsmn-vad 到自缓存）。"""
    seen: dict[str, Any] = {}

    class Probe:
        def __init__(self, model: str, **kw: Any) -> None:
            seen.update(model=model, **kw)

        def generate(self, **_kw: Any) -> list[dict[str, Any]]:
            return []

    monkeypatch.setitem(sys.modules, "funasr", type("m", (), {"AutoModel": Probe}))
    engine = ParaformerEngine(
        models_dir=tmp_path / "nope",
        vad_model_dir=tmp_path / "nope" / "fsmn-vad",
        spk_model_dir=tmp_path / "nope" / "campplus",
    )
    engine._ensure_model()

    assert seen["model"] == _REPO_ID
    assert seen["vad_model"] == "fsmn-vad"
    assert seen["spk_model"] == "cam++"
    assert seen["spk_mode"] == "vad_segment", "标点模型不挂，显式 vad_segment 免库内假警报"


def test_no_diarization_no_spk_kwargs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    class Probe:
        def __init__(self, model: str, **kw: Any) -> None:
            seen.update(model=model, **kw)

        def generate(self, **_kw: Any) -> list[dict[str, Any]]:
            return []

    monkeypatch.setitem(sys.modules, "funasr", type("m", (), {"AutoModel": Probe}))
    ParaformerEngine(models_dir=tmp_path / "nope")._ensure_model()

    assert "spk_model" not in seen and "vad_model" not in seen


def test_num_speakers_zero_is_auto(tmp_path: Path, fake_funasr: type[_FakeAutoModel]) -> None:
    engine = ParaformerEngine(
        models_dir=tmp_path / "nope", spk_model_dir=tmp_path, num_speakers=3
    )
    engine._ensure_model().reply = [{"text": "你", "timestamp": [[0, 300]]}]
    engine.transcribe(Path("a.wav"))
    assert fake_funasr.instances[0].generate_calls[0]["preset_spk_num"] == 3

    auto = ParaformerEngine(models_dir=tmp_path / "nope", spk_model_dir=tmp_path)
    auto._ensure_model().reply = [{"text": "你", "timestamp": [[0, 300]]}]
    auto.transcribe(Path("a.wav"))
    assert "preset_spk_num" not in fake_funasr.instances[1].generate_calls[0], "0=聚类自动判人数"


def test_sentence_info_assigns_speaker_by_majority_overlap(
    tmp_path: Path, fake_funasr: type[_FakeAutoModel]
) -> None:
    """重叠时长多数归属：段大部分时间在 A 的区间里就归 A，与 B 只擦边的不管。"""
    engine = ParaformerEngine(models_dir=tmp_path / "nope", spk_model_dir=tmp_path)
    engine._ensure_model().reply = [{
        "text": "你好呀再见",
        "timestamp": [[0, 300], [300, 500], [500, 800], [2000, 2400], [2400, 2700]],
        "sentence_info": [
            {"text": "你好", "start": 0, "end": 800, "spk": 0},
            {"text": "再见", "start": 2000, "end": 2700, "spk": 1},
        ],
    }]

    segments = engine.transcribe(Path("a.wav"))

    assert [s.speaker for s in segments] == ["角色A", "角色B"]


def test_uncovered_segment_keeps_speaker_none() -> None:
    """与任何说话人区间都不重叠的段不编造归属。"""
    from dramaclip.engines.analysis.models import AsrSegment
    from dramaclip.engines.analysis.transcriber import _assign_speakers

    seg = AsrSegment(start=10.0, end=11.0, text="无人认领")
    out = _assign_speakers([seg], [(0.0, 1.0, 0)])
    assert out[0].speaker is None


def test_spk_spans_skip_malformed_entries() -> None:
    from dramaclip.engines.analysis.transcriber import _spk_spans

    assert _spk_spans([{"sentence_info": [
        {"start": 0, "end": 500, "spk": 0},
        {"start": "x", "end": 500, "spk": 0},   # 非法 start
        {"start": 500, "end": 500, "spk": 0},   # 零长区间
        {"start": 600, "spk": 1},               # 缺 end
    ]}]) == [(0.0, 0.5, 0)]


def test_pause_split_shifts_word_timestamps_with_clip_anchor(
    tmp_path: Path,
    fake_funasr: type[_FakeAutoModel],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """多 clip 锚定必须连词级时间戳一起平移：只移 start/end 会让 refine 字流坍缩。

    真机第1集实锤：46 段全挤 0-11.58s、起点乱序、微负边界——词锚留在 clip 内，
    refine 字流按词取时间，整份时间轴塌成首 clip 跨度。
    """
    from dramaclip.engines.analysis import pause_split

    clips = [
        pause_split.Clip(start=0.0, end=2.0),
        pause_split.Clip(start=10.0, end=12.0),
    ]
    monkeypatch.setattr(pause_split, "speech_clips", lambda _wav, **_kw: clips)
    monkeypatch.setattr(
        pause_split,
        "split_wav",
        lambda _wav, _clips, _work: [
            (clip, tmp_path / f"clip-{index}.wav")
            for index, clip in enumerate(_clips)
        ],
    )

    class _ClipModel:
        """每次 generate 返回相对 clip 的原生时间戳（首 clip 从 0 起、次 clip 也从 0 起）。"""

        def __init__(self) -> None:
            self.calls = 0

        def generate(self, **_kw: Any) -> list[dict[str, Any]]:
            self.calls += 1
            base = 0.0 if self.calls == 1 else 10.0 - 10.0  # 两 clip 的词戳都从各自 0 起
            return [{
                "text": "你好再见",
                "timestamp": [
                    [int(base * 1000), int((base + 0.3) * 1000)],
                    [int((base + 0.3) * 1000), int((base + 0.6) * 1000)],
                    [int((base + 1.0) * 1000), int((base + 1.4) * 1000)],
                    [int((base + 1.4) * 1000), int((base + 1.8) * 1000)],
                ],
            }]

    engine = ParaformerEngine(models_dir=tmp_path / "nope")
    engine._model = _ClipModel()  # noqa: SLF001 - 直注入，绕过 funasr 构造

    segments = engine.transcribe(Path("a.wav"))

    assert len(segments) == 2
    first, second = segments
    assert (first.start, first.end) == (0.0, 1.8)
    assert (second.start, second.end) == (10.0, 11.8), "第二 clip 的段必须平移 clip 起点 10s"
    assert [(w.start, w.end) for w in second.words] == [
        (10.0, 10.3), (10.3, 10.6), (11.0, 11.4), (11.4, 11.8),
    ], "词级时间戳必须随 clip 锚定整体平移：留在 clip 相对值会让 refine 字流整份坍缩"
    assert [(w.start, w.end) for w in first.words] == [
        (0.0, 0.3), (0.3, 0.6), (1.0, 1.4), (1.4, 1.8),
    ]
