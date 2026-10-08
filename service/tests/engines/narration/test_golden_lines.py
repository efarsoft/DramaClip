"""LLM 金句提取（2026-10-08 业主裁决「规则打分不可靠，LLM 提取」）。

编号回填零幻觉：金句原文永远来自真实台词，编号越界/重复/非整数丢弃；
LLM 不可用 → None，调用方回退规则打分（降级不可见）。
"""

from __future__ import annotations

from dramaclip.engines.analysis.models import AsrSegment
import pytest

from dramaclip.engines.narration import golden_lines
from dramaclip.engines.semantic.llm_client import LlmUnavailable


class _FakeLlm:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def chat_json(self, system: str, user: str):
        self.calls.append((system, user))
        if self.error is not None:
            raise self.error
        return self.result


def _asr() -> list[AsrSegment]:
    return [
        AsrSegment(start=0.0, end=2.0, text="今天天气不错"),
        AsrSegment(start=2.0, end=5.0, text="我陈平安，唯有一剑，可搬山，倒海"),
        AsrSegment(start=5.0, end=7.0, text="他带了些干粮"),
        AsrSegment(start=7.0, end=10.0, text="你连给他提鞋都不配"),
    ]


def test_picks_lines_by_llm_ids_in_rank_order() -> None:
    llm = _FakeLlm({"ids": [4, 2]})
    spans = golden_lines.pick_golden_lines(
        llm, [(i + 1, s.start, s.end, s.text) for i, s in enumerate(_asr())]
    )
    assert spans == [(7.0, 10.0), (2.0, 5.0)], "按 LLM 给出的传播力排序回传"


def test_invalid_ids_are_dropped() -> None:
    llm = _FakeLlm({"ids": [99, 2, 2, "x", 1]})
    spans = golden_lines.pick_golden_lines(
        llm, [(i + 1, s.start, s.end, s.text) for i, s in enumerate(_asr())]
    )
    assert spans == [(2.0, 5.0), (0.0, 2.0)], "越界/重复/非整数丢弃"


def test_llm_unavailable_raises_with_reason_at_batch_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无兜底裁决（2026-10-08）：批量入口失败即抛带原因的 ValueError，
    不静默降级成规则打分。"""
    import pytest

    class _FailLlm:
        def chat_json(self, _system: str, _user: str):
            raise LlmUnavailable("端点挂了")

    monkeypatch.setattr(golden_lines, "LlmClient", lambda *_a, **_k: _FailLlm())
    with pytest.raises(ValueError, match="金句提取失败.*端点挂了"):
        golden_lines.pick_for_material(
            {"llm.base_url": "https://x/v1", "llm.model": "m"},
            {"ep1": [(1, 0.0, 2.0, "x")]},
        )


def test_empty_lines_returns_none() -> None:
    """空台词列表不是失败：该集无台词可挑，回 None 由调用方决策。"""
    llm = _FakeLlm({"ids": [1]})
    assert golden_lines.pick_golden_lines(llm, []) is None


def test_pick_for_material_unconfigured_raises() -> None:
    import pytest

    with pytest.raises(ValueError, match="金句提取需要文本模型"):
        golden_lines.pick_for_material({"llm.model": ""}, {"ep1": [(1, 0.0, 2.0, "x")]})
