"""复述测试（retell）：无上下文闭卷复述的判定规则与降级。"""

from __future__ import annotations

from typing import Any

import pytest

from dramaclip.engines.narration.retell import _FAIL_CONFUSIONS, retell_check
from dramaclip.engines.semantic.llm_client import LlmUnavailable


class _StubClient:
    """桩 LlmClient：chat_json 返回预置 answer，记录收到的 prompt。"""

    def __init__(self, answer: Any, fail: bool = False) -> None:
        self._answer = answer
        self._fail = fail
        self.calls: list[tuple[str, str]] = []

    def chat_json(self, system: str, user: str, temperature: float | None = None) -> Any:
        if self._fail:
            raise LlmUnavailable("LLM 未配置")
        self.calls.append((system, user))
        return self._answer


def _answer(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "retell": "男主想为女儿筹钱，被卷入铸钱大案，最后沉冤得雪。",
        "confusions": [],
        "has_goal": True,
        "has_ending": True,
    }
    base.update(overrides)
    return base


def test_retell_pass_on_clean_answer() -> None:
    client = _StubClient(_answer())
    report = retell_check("第一句。\n第二句。", client)  # type: ignore[arg-type]
    assert report.passed is True
    assert report.reasons == []
    # 稿子作为 user 消息原样进 prompt；system 是观众设定
    assert client.calls[0][1] == "第一句。\n第二句。"
    assert "普通观众" in client.calls[0][0]


def test_retell_fails_on_missing_goal_or_ending() -> None:
    report = retell_check("稿子", _StubClient(_answer(has_goal=False)))  # type: ignore[arg-type]
    assert report.passed is False
    assert "主角目标不明" in report.reasons
    report = retell_check("稿子", _StubClient(_answer(has_ending=False)))  # type: ignore[arg-type]
    assert report.passed is False
    assert "结局不明" in report.reasons


def test_retell_fails_when_confusions_reach_threshold() -> None:
    confusions = [
        {"quote": f"片段{i}", "issue": "dense", "note": "太密"} for i in range(_FAIL_CONFUSIONS)
    ]
    report = retell_check("稿子", _StubClient(_answer(confusions=confusions)))  # type: ignore[arg-type]
    assert report.passed is False
    assert f"卡点达 {_FAIL_CONFUSIONS} 处" in report.reasons
    # 低于阈值（1-3 处）仍通过——单点卡顿可能是观众个体差异
    few = retell_check("稿子", _StubClient(_answer(confusions=confusions[:2])))  # type: ignore[arg-type]
    assert few.passed is True


def test_retell_sanitizes_malformed_confusions() -> None:
    answer = _answer(confusions=[{"quote": 123, "issue": None}, "不是字典", {"note": "缺 quote"}])
    report = retell_check("稿子", _StubClient(answer))  # type: ignore[arg-type]
    # 非字典条目丢弃；字典条目字段强制转字符串截断
    assert len(report.confusions) == 2
    assert all(set(c) == {"quote", "issue", "note"} for c in report.confusions)
    assert all(isinstance(v, str) for c in report.confusions for v in c.values())


def test_retell_raises_on_non_dict_answer() -> None:
    with pytest.raises(ValueError, match="JSON 对象"):
        retell_check("稿子", _StubClient(["不是对象"]))  # type: ignore[arg-type]


def test_retell_propagates_llm_unavailable() -> None:
    # 软质检的降级发生在调用方（管线/gateway 捕获），模块本身如实抛出
    with pytest.raises(LlmUnavailable):
        retell_check("稿子", _StubClient(None, fail=True))  # type: ignore[arg-type]
