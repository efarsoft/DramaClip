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
        "dramaclip.engines.analysis.llm_refine.client_for",
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
    assert [s.text for s in outcome.segments] == ["我穿成崇祯皇帝。", "干的第一件事。"]
    assert all(s.source == "llm_refined" for s in outcome.segments), "精炼段必须带身份标记"
    assert outcome.segments[0].start == pytest.approx(0.0), "窗锚定：行时间=窗起点"
    assert outcome.segments[0].end == pytest.approx(1.5), "窗锚定：行时间=窗终点"
    assert outcome.segments[1].start == pytest.approx(2.0)
    assert outcome.segments[1].end == pytest.approx(3.5)
    assert "字幕窗" in _FakeClient.last_user, "字幕窗列表进提示词"


def test_refine_band_anchor_rejects_document_window_hijack(monkeypatch: pytest.MonkeyPatch) -> None:
    """带内锚定（EP6 真机 2026-10-20）：字据特写的 OCR 条目不得劫持画外音台词。

    场景：开头是字据特写+画外音——OCR 产出「二A10」垃圾窗与字据翻页窗；
    中段句的「皇后/首饰」bigram 与字据文本部分亲和，盲目比例分配曾把前 7 句
    全塞进 1.5 秒窗（时间戳坍缩=台词被吞）。修复后：亲和不达标的窗不锚；
    亲和达标但越出「前段结束→下一句实测起点」时间带的窗也不锚——两套节拍
    永不劫持彼此的时间位置。
    """
    windows = [
        OcrSegment(start=2.5, end=4.0, text="二A10"),
        OcrSegment(start=8.5, end=9.5,
                   text="此银雨整伍万两以解燃眉之急今有周皇后将私有首饰一批"),
    ]
    raw = [_seg("有些疑问陛下请讲老臣定当如实禀报好皇后变卖首饰", start=2.5)]
    sentences = ["有些疑问。", "陛下，请讲。", "老臣定当如实禀报。", "好，皇后变卖首饰。"]
    outcome = _run(monkeypatch, sentences, raw, windows=windows)
    starts = [seg.start for seg in outcome.segments]
    assert starts == sorted(starts), "时序单调：假窗不得造成倒跳"
    assert all(seg.end <= 9.5 + 0.31 for seg in outcome.segments if seg.start < 8.0), (
        "开头台词不得被字据翻页窗劫持到 8.5s 之后"
    )



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
    assert outcome.segments[0].text == "就是杀了大明两大蛀虫。"


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
    assert outcome.segments[0].text == "甲乙丙丁。", "非法替换回退原字"


def test_refine_repairs_unbacked_insertion(monkeypatch: pytest.MonkeyPatch) -> None:
    """无据插入 → 丢弃（修复语义：掉字不炸整集）。"""
    raw = [_seg("甲乙丙丁", start=0.0)]
    outcome = _run(monkeypatch, ["甲乙丙丁戊"], raw, ocr_text="")
    assert outcome.applied
    assert "自动修复 1 处" in outcome.detail
    assert outcome.segments[0].text == "甲乙丙丁。"


def test_refine_keeps_ocr_backed_insertion(monkeypatch: pytest.MonkeyPatch) -> None:
    """补漏字：ASR 漏听（BGM 盖住）而字幕有据 → 保留补字，不按无据插入丢弃。

    真机 2026-10-20：字流「一件事」、字幕「干的第一件事」——提示词曾禁止增字，
    护栏的 OCR 有据通道形同虚设，吞字补不回来（业主实锤）。
    """
    raw = [_seg("一件事就是杀了大明两大蛀虫", start=1.5)]
    outcome = _run(
        monkeypatch,
        ["干的第一件事，就是杀了大明两大蛀虫。"],
        raw,
        ocr_text="我穿成崇祯皇帝干的第一件事就是杀了大明两大蛀虫",
    )
    assert outcome.applied
    assert outcome.segments[0].text == "干的第一件事，就是杀了大明两大蛀虫。"


def test_refine_llm_unconfigured_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = [_seg("甲乙丙丁", start=0.0)]
    monkeypatch.setattr(
        "dramaclip.engines.analysis.llm_refine.client_for",
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
        "dramaclip.engines.analysis.llm_refine.client_for", lambda _s: _BrokenClient()
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
        "dramaclip.engines.analysis.llm_refine.client_for", lambda _s: _ShapedClient()
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


def test_stream_mismatch_still_refines_with_placeholder_stamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """词戳与文本字数不符（OCR 补字场景，source=ocr_fixed 的正常形状）→ 不再判坏数据：
    按文本字流精炼，缺戳字时间由 _rebuild_words 插值补齐。"""
    broken = AsrSegment(
        start=0.0, end=1.0, text="甲乙丙丁", words=[WordSpan(start=0.0, end=0.5, word="甲")]
    )
    outcome = _run(monkeypatch, ["甲乙丙丁"], [broken], ocr_text="")
    assert outcome.applied, "OCR 补字段不再跳过精炼"
    assert outcome.segments[0].words, "重建字戳不得为空"


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


def test_refine_carries_speaker_through_rebuild(monkeypatch: pytest.MonkeyPatch) -> None:
    """说话人透传（E2-5 追加修复）：refine 重建段不得丢 speaker——自动音色提取靠它。

    两段各带说话人、LLM 按原边界切两句 → 各自保留来源说话人；
    LLM 跨说话人并句 → 句内同源不成立，speaker 留 None（不编造归属）。
    """
    seg_a = AsrSegment(
        start=0.0,
        end=0.4,
        text="你好",
        speaker="角色A",
        words=[WordSpan(start=0.0, end=0.2, word="你"), WordSpan(start=0.2, end=0.4, word="好")],
    )
    seg_b = AsrSegment(
        start=1.0,
        end=1.4,
        text="再见",
        speaker="角色B",
        words=[WordSpan(start=1.0, end=1.2, word="再"), WordSpan(start=1.2, end=1.4, word="见")],
    )
    outcome = _run(monkeypatch, ["你好，", "再见"], [seg_a, seg_b])
    assert outcome.applied is True
    assert [(s.text, s.speaker) for s in outcome.segments] == [
        ("你好。", "角色A"),
        ("再见。", "角色B"),
    ], "句边界不跨说话人：各自保留来源标签；逗号收尾兜底替换为句号"

    # 跨说话人并句：同源不成立 → speaker=None，不编造归属
    outcome = _run(monkeypatch, ["你好再见"], [seg_a, seg_b])
    assert outcome.segments[0].speaker is None, "跨说话人并句不编造归属"
