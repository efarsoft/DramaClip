"""llm_refine：断句+校对单次调用的护栏分支、拼音边界与回退链。"""

from __future__ import annotations

from typing import Any

import pytest

from dramaclip.engines.analysis.llm_refine import RefineOutcome, refine_segments
from dramaclip.engines.analysis.models import AsrSegment, OcrSegment, WordSpan
from dramaclip.engines.semantic.llm_client import LlmConfig

_SETTINGS = {
    "llm.base_url": "http://llm.test",
    "llm.api_key": "sk-test",
    "llm.model": "test-model",
}


def _win(start: float, end: float, text: str) -> OcrSegment:
    return OcrSegment(start=start, end=end, text=text, conf=0.9)


def _seg(text: str, start: float = 0.0) -> AsrSegment:
    """构造字戳逐字 0.1s 的段（text 的内容字逐一配 WordSpan）。"""
    words = [
        WordSpan(start=start + i * 0.1, end=start + (i + 1) * 0.1, word=ch)
        for i, ch in enumerate(text)
    ]
    return AsrSegment(start=start, end=start + len(text) * 0.1, text=text, words=words)


class _FakeClient:
    """桩客户端：固定回复 + 捕获 user 提示词供断言。"""

    config = LlmConfig(base_url="http://llm.test", api_key="sk-test", model="test-model")
    reply: list[str] = []
    last_user = ""

    def chat_json(
        self, _system: str, user: str, temperature: float | None = None
    ) -> dict[str, Any]:
        _FakeClient.last_user = user
        return {"sentences": list(_FakeClient.reply)}


def _run(
    monkeypatch: pytest.MonkeyPatch,
    reply: list[str],
    segments: list[AsrSegment],
    ocr_text: str = "",
    windows: list[OcrSegment] | None = None,
) -> RefineOutcome:
    _FakeClient.reply = reply
    monkeypatch.setattr(
        "dramaclip.engines.analysis.llm_refine.llm_from_settings",
        lambda _s: _FakeClient(),
    )
    return refine_segments(
        segments,
        ocr_segments=(
            windows if windows is not None else ([_win(0.0, 1.0, ocr_text)] if ocr_text else [])
        ),
        project_name="大明：灭国前，我觉醒了",
        hotwords="东厂 崇祯 锦衣卫",
        settings=_SETTINGS,
    )


def test_refine_splits_and_fixes_homophones(monkeypatch: pytest.MonkeyPatch) -> None:
    """并句+同音错字一次修：传承→穿成（同音）；行时间=字幕窗锚定（窗锚定核心断言）。"""
    raw = [_seg("我传承崇祯皇帝干的第一件事", start=1.5)]
    outcome = _run(
        monkeypatch,
        ["我穿成崇祯皇帝", "干的第一件事"],
        raw,
        windows=[_win(0.0, 1.5, "我穿成崇祯皇帝"), _win(2.0, 3.5, "干的第一件事")],
    )
    assert outcome.applied
    assert [s.text for s in outcome.segments] == ["我穿成崇祯皇帝", "干的第一件事"]
    assert all(s.source == "llm_refined" for s in outcome.segments), "精炼段必须带身份标记"
    assert outcome.segments[0].start == pytest.approx(0.0), "窗锚定：行时间=窗起点"
    assert outcome.segments[0].end == pytest.approx(1.5), "窗锚定：行时间=窗终点"
    assert outcome.segments[1].start == pytest.approx(2.0)
    assert outcome.segments[1].end == pytest.approx(3.5)
    assert "字幕窗" in _FakeClient.last_user, "字幕窗列表进提示词"


def test_refine_near_pinyin_with_ocr_evidence_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """蛀虫修正：蛀/诸同音过；虫/传近音（同声母）+ 字幕有据 → 通过。"""
    raw = [_seg("就是杀了大明两大诸传", start=3.5)]
    outcome = _run(
        monkeypatch,
        ["就是杀了大明两大蛀虫"],
        raw,
        windows=[_win(3.5, 5.0, "就是杀了大明两大蛀虫"), _win(6.0, 8.0, "一个是权势滔天")],
    )
    assert outcome.applied
    assert outcome.segments[0].text == "就是杀了大明两大蛀虫"


def test_refine_repairs_content_deletion(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM 丢掉的内容 → 护栏自动还原原字（修复而非拒绝）。"""
    raw = [_seg("就是杀了大明两大蛀虫", start=3.5)]
    outcome = _run(monkeypatch, ["就是杀了大明"], raw, ocr_text="")
    assert outcome.applied
    assert "自动修复 4 处" in outcome.detail
    assert "大明两大蛀虫" in outcome.segments[0].text, "被删内容完整还原"


def test_refine_repairs_unrelated_substitution(monkeypatch: pytest.MonkeyPatch) -> None:
    """丁→戊 既不同音也非近音 → 回退原字（防 LLM 改写句式的幻觉）。"""
    raw = [_seg("甲乙丙丁", start=0.0)]
    outcome = _run(monkeypatch, ["甲乙丙戊"], raw, ocr_text="")
    assert outcome.applied
    assert "自动修复 1 处" in outcome.detail
    assert outcome.segments[0].text == "甲乙丙丁", "非法替换回退原字"


def test_refine_repairs_unbacked_insertion(monkeypatch: pytest.MonkeyPatch) -> None:
    """无据插入 → 丢弃（修复语义：掉字不炸整集）。"""
    raw = [_seg("甲乙丙丁", start=0.0)]
    outcome = _run(monkeypatch, ["甲乙丙丁戊"], raw, ocr_text="")
    assert outcome.applied
    assert "自动修复 1 处" in outcome.detail
    assert outcome.segments[0].text == "甲乙丙丁"


def test_refine_llm_unconfigured_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = [_seg("甲乙丙丁", start=0.0)]
    monkeypatch.setattr(
        "dramaclip.engines.analysis.llm_refine.llm_from_settings",
        lambda _s: _FakeClient(),
    )
    outcome = refine_segments(
        raw, ocr_segments=[], project_name="剧", hotwords="", settings={"llm.base_url": ""}
    )
    assert not outcome.applied
    assert outcome.detail == "LLM 未配置"


def test_refine_llm_failure_falls_back_with_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenClient:
        config = LlmConfig(base_url="http://llm.test", api_key="k", model="m")

        def chat_json(self, *_a: object, **_k: object) -> dict[str, Any]:
            raise ValueError("boom")

    monkeypatch.setattr(
        "dramaclip.engines.analysis.llm_refine.llm_from_settings", lambda _s: _BrokenClient()
    )
    raw = [_seg("甲乙丙丁", start=0.0)]
    outcome = refine_segments(
        raw, ocr_segments=[], project_name="剧", hotwords="", settings=_SETTINGS
    )
    assert not outcome.applied
    assert "boom" in outcome.detail
    assert outcome.segments[0].text == "甲乙丙丁", "回退=原生分段"


def test_refine_retries_once_on_bad_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """首次输出形状不符 → 强化重试一次（捕获 user 里的强化尾巴）。"""
    calls: list[str] = []

    class _ShapedClient:
        config = LlmConfig(base_url="http://llm.test", api_key="k", model="m")

        def chat_json(
            self, _system: str, user: str, temperature: float | None = None
        ) -> dict[str, Any]:
            calls.append(user)
            if len(calls) == 1:
                return {"sentences": "不是数组"}
            return {"sentences": ["甲乙丙丁"]}

    monkeypatch.setattr(
        "dramaclip.engines.analysis.llm_refine.llm_from_settings", lambda _s: _ShapedClient()
    )
    outcome = refine_segments(
        [_seg("甲乙丙丁", start=0.0)],
        ocr_segments=[],
        project_name="剧",
        hotwords="",
        settings=_SETTINGS,
    )
    assert outcome.applied and len(calls) == 2
    assert "JSON 格式" in calls[1], "重试带格式强化"


def test_stream_mismatch_falls_back_before_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """词戳字数与文本字数不符（坏数据）→ 不调 LLM 直接回退。"""
    broken = AsrSegment(
        start=0.0, end=1.0, text="甲乙丙丁", words=[WordSpan(start=0.0, end=0.5, word="甲")]
    )
    outcome = _run(monkeypatch, ["甲乙丙丁"], [broken], ocr_text="")
    assert not outcome.applied
    assert "字流校验失败" in outcome.detail


def test_refined_segments_preserve_word_stamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """精炼产物必须随段重建字戳：丢了下游 OCR×ASR 融合整集回落纯 ASR。

    真机 EP1 实测：精炼产物无 words 字段 → 融合永远回落 → 字幕窗对齐名存实亡。
    修复 = _to_segments 从修复后条目重建 words（实测优先、无据插字插值）。
    """
    seg = _seg("皇后变卖首饰，才凑出五千两")
    outcome = _run(
        monkeypatch,
        ["皇后变卖首饰，才凑出五千两", "国丈地窖里的银子，转眼全成了借款"],
        [seg],
        windows=[
            _win(0.0, 2.6, "皇后变卖首饰"),
            _win(2.6, 5.0, "才凑出五千两"),
            _win(5.0, 7.4, "国丈地窖里的银子"),
        ],
    )
    assert outcome.applied is True
    assert len(outcome.segments) >= 2
    for refined in outcome.segments:
        assert refined.words, f"精炼段丢失字戳: {refined.text}"
        # 字戳内容与文本内容字一一对应（融合 _char_units 的对齐前提）
        stream = "".join(w.word for w in refined.words)
        content = "".join(ch for ch in refined.text if ch not in "，。！？、；：")
        assert stream == content, f"字戳流与文本内容字不一致: {stream!r} vs {content!r}"
