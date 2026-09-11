"""narration.copywriter：槽位 → LLM → 文案。降级禁止，故所有失败路径都必须是异常。"""

from __future__ import annotations

from typing import Any

import pytest

from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.narration import copywriter
from dramaclip.engines.narration.models import StrategySpec
from dramaclip.engines.narration.modes_w8 import build_full
from dramaclip.engines.semantic.llm_client import LlmUnavailable
from dramaclip.engines.semantic.models import ConflictScore

_SETTINGS = {
    "llm.base_url": "http://llm.test/v1",
    "llm.api_key": "sk-test",
    "llm.model": "test-model",
    "_project_name": "透视眼",
    "_genre": "复仇",
    "_style_directives": "强节奏，多用短句砸爽点",
}

_SCENES = [
    ConflictScore(scene_index=i, start=i * 12.0, end=i * 12.0 + 10.0, score=s)
    for i, s in enumerate([60, 85, 45, 90])
]

_SEGMENTS = [
    AsrSegment(start=i * 12.0 + 1, end=i * 12.0 + 5, text=f"第 {i} 幕的原话")
    for i in range(4)
]


class FakeLlm:
    """按队列应答 chat_json，记录每次 user prompt 供断言。"""

    calls: list[str] = []
    queue: list[Any] = []

    def __init__(self, _config: Any, timeout_s: float = 60.0) -> None:
        self.timeout_s = timeout_s

    def chat_json(self, _system: str, user: str) -> Any:
        FakeLlm.calls.append(user)
        item = FakeLlm.queue.pop(0) if len(FakeLlm.queue) > 1 else FakeLlm.queue[0]
        if isinstance(item, Exception):
            raise item
        return item


def _plan():
    return build_full("ep1", _SCENES, StrategySpec(min_duration_s=10))


def _lines() -> dict[str, Any]:
    return {
        "lines": [
            {"id": f"full-{i + 1}", "text": f"第 {i + 1} 条解说"}
            for i in range(len(_SCENES))
        ]
    }


@pytest.fixture()
def llm(monkeypatch: pytest.MonkeyPatch) -> Any:
    FakeLlm.calls = []
    FakeLlm.queue = []
    monkeypatch.setattr(copywriter, "LlmClient", FakeLlm)
    return FakeLlm


def test_fills_every_slot_and_flips_planner(llm: Any) -> None:
    llm.queue = [_lines()]
    plan = copywriter.write_plan_copy(_plan(), _SEGMENTS, _SETTINGS)
    assert plan.planner == "llm_script"
    assert [t.text for t in plan.narration_texts] == [
        "第 1 条解说", "第 2 条解说", "第 3 条解说", "第 4 条解说"
    ]


def test_prompt_carries_slot_window_and_transcript(llm: Any) -> None:
    llm.queue = [_lines()]
    copywriter.write_plan_copy(_plan(), _SEGMENTS, _SETTINGS)
    prompt = llm.calls[0]
    assert "透视眼" in prompt and "复仇" in prompt
    assert "强节奏" in prompt, "口味层指令未注入"
    assert "[full-2]" in prompt and "高潮" in prompt, "槽位职责未进 prompt"
    assert "第 1 幕的原话" in prompt, "素材台词未进 prompt"


def test_missing_slot_raises(llm: Any) -> None:
    llm.queue = [{"lines": [{"id": "full-1", "text": "只写了一条"}]}]
    with pytest.raises(ValueError, match="漏了 3 个槽位"):
        copywriter.write_plan_copy(_plan(), _SEGMENTS, _SETTINGS)


def test_retries_once_then_raises(llm: Any) -> None:
    llm.queue = [LlmUnavailable("网关 502"), {"lines": []}]
    with pytest.raises(ValueError, match="编剧"):
        copywriter.write_plan_copy(_plan(), _SEGMENTS, _SETTINGS)
    assert len(llm.calls) == 2, "应重试一次"


def test_unconfigured_llm_raises_before_prompt(llm: Any) -> None:
    settings = dict(_SETTINGS)
    settings["llm.model"] = ""
    with pytest.raises(LlmUnavailable, match="文案必须由编剧模型产出"):
        copywriter.write_plan_copy(_plan(), _SEGMENTS, settings)
    assert llm.calls == []


def test_oversize_line_rejected(llm: Any) -> None:
    """超出 60 字 ×1.2 容忍即判没答：重试一次仍超长就抛，不得把长句塞进成片。"""
    over = "长" * 80
    llm.queue = [
        {"lines": [{"id": f"full-{i + 1}", "text": over} for i in range(len(_SCENES))]}
    ]
    with pytest.raises(ValueError, match="未产出合格文案"):
        copywriter.write_plan_copy(_plan(), _SEGMENTS, _SETTINGS)
    assert len(llm.calls) == 2, "超长应触发一次重问"
