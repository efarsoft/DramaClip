"""候选标题卡：产出契约（8 条 / 每条 20 字内 / 六类实证句式 / 不剧透 / 附发布物料）要写死。"""

from __future__ import annotations

import json
from typing import Any

import pytest

from dramaclip.engines.narration import titles
from dramaclip.engines.semantic.llm_client import LlmUnavailable

_PLAN = {"narration_texts": [{"id": "n0", "text": "她被全家逼着嫁给残废将军。"}]}


class FakeClient:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.systems: list[str] = []

    def chat_json(self, system: str, _user: str, temperature: float = 0.3) -> Any:
        self.systems.append(system)
        return self.payload


def _generate(
    monkeypatch, payload: Any, **settings: str
) -> tuple[dict[str, Any], FakeClient]:
    client = FakeClient(payload)
    monkeypatch.setattr(titles, "LlmClient", lambda *a, **k: client)
    base = {"llm.base_url": "https://x/v1", "llm.model": "m", "llm.api_key": "k"}
    return titles.generate(_PLAN, {**base, **settings}), client


def test_prompt_pins_the_count_and_the_six_patterns(monkeypatch) -> None:
    """六类句式来自双平台 280+ 条高互动样本的实证归纳，每类都是可模仿的完整套路。"""
    _, client = _generate(monkeypatch, {"titles": ["甲"]})
    system = client.systems[0]
    assert "8 条候选视频标题" in system, "条数没写死，模型会给 6~9 条"
    patterns = ("冲突一句话", "悬念反问", "金句宣言", "行为指令", "人物关系三段式", "极简剧名式")
    for pattern in patterns:
        assert pattern in system, f"六类句式少了「{pattern}」这一路"
    for key in ('"titles"', '"caption"', '"tags"'):
        assert key in system, f"发布物料 {key} 没进 JSON 契约"
    assert "禁止照抄示例" in system, "示例句不隔离会被模型当真实剧情复读"


def test_prompt_keeps_the_anti_spoiler_and_length_caps(monkeypatch) -> None:
    _, client = _generate(monkeypatch, {"titles": ["甲"]})
    system = client.systems[0]
    assert "不超过 20 个字" in system
    assert "严禁剧透" in system


def test_quota_rewording_stays_withdrawn(monkeypatch) -> None:
    """「各占一些→各 2 条」「8 条→正好 8 条」的改写实测更差，已撤回：
    同机同稿（524 字）各 6 批，每批条数都合规，但超 20 字数
    old 0/48 → 新措辞 8/48 → 再收「8-18 字＋整条作废」11/40。
    当初以为「数字冲击 0/29」是措辞失灵的判断也不成立——那是只用
    ch.isdigit() 数数字的读数错误，中文数字（三冠王、百年球局）没算进去；
    重测带数字比例 old 32/48，本就没有失灵。六类句式同样只列方向不配额。
    """
    _, client = _generate(monkeypatch, {"titles": ["甲"]})
    system = client.systems[0]
    assert "各 2 条" not in system
    assert "正好 8 条" not in system


def test_floor_override_replaces_the_titles_card(monkeypatch) -> None:
    """可编辑卡必须真的生效：改了就发新的，不能照旧发默认。"""
    _, client = _generate(
        monkeypatch, {"titles": ["甲"]}, **{"prompt.titles_system": "只回 JSON。"}
    )
    assert client.systems[0] == "只回 JSON。"


def test_unconfigured_llm_says_where_to_fix(monkeypatch) -> None:
    with pytest.raises(LlmUnavailable, match="引擎"):
        titles.generate(_PLAN, {})


def test_blank_titles_from_model_are_not_shipped(monkeypatch) -> None:
    out, _ = _generate(monkeypatch, {"titles": ["甲", "  ", "", None]})
    assert [t["text"] for t in out["titles"]] == ["甲"]
    assert out["titles"][0]["selected"] is True


def test_publish_meta_is_cleaned_from_the_same_roundtrip(monkeypatch) -> None:
    """caption 去空白；tags 去 #/去空/去重；同一往返产出，不额外花一次调用。"""
    payload = {
        "titles": ["甲"],
        "caption": " 她替嫁三年。 ",
        "tags": ["#爽剧", "  ", "逆袭", "#爽剧", None, 3],
    }
    out, _ = _generate(monkeypatch, payload)
    assert out["caption"] == "她替嫁三年。"
    assert out["tags"] == ["爽剧", "逆袭"]


def test_publish_meta_absent_from_old_style_output(monkeypatch) -> None:
    """老输出只有 titles：caption/tags 安静给空，不挡标题。"""
    out, _ = _generate(monkeypatch, {"titles": ["甲"]})
    assert out["caption"] is None
    assert out["tags"] == []


def test_no_copy_raises_instead_of_inventing_titles(monkeypatch) -> None:
    with pytest.raises(ValueError, match="没有解说文案"):
        titles.generate({"narration_texts": []}, {"llm.base_url": "u", "llm.model": "m"})


# --------------------------------------------------------------- 留痕（立案C）
# 标题忽好忽坏只能靠人眼盯，唯一的复核证据是当时到底发了什么、回了什么。

_BASE = {"llm.base_url": "https://x/v1", "llm.model": "m", "llm.api_key": "k"}


def _trace(monkeypatch, payload: Any, tmp_path):
    """跑一次带留痕的生成；生成抛不抛都要把留痕读回来——留痕正是复核证据。"""
    client = FakeClient(payload)
    monkeypatch.setattr(titles, "LlmClient", lambda *a, **k: client)
    trace = tmp_path / "titles_plan1.json"
    outcome = "ok"
    try:
        titles.generate(_PLAN, _BASE, trace_path=trace)
    except ValueError as exc:
        outcome = str(exc)
    return outcome, json.loads(trace.read_text(encoding="utf-8"))


def test_trace_keeps_the_prompt_and_the_answer(monkeypatch, tmp_path) -> None:
    outcome, blob = _trace(monkeypatch, {"titles": ["她一杆清台"]}, tmp_path)
    assert outcome == "ok"
    assert "她被全家逼着嫁给残废将军" in blob["user"], "解说文案没进留痕"
    assert blob["raw"] == {"titles": ["她一杆清台"]}
    assert blob["accepted"] == 1


def test_a_rejected_answer_is_traced_too(monkeypatch, tmp_path) -> None:
    """整批标题被判空而抛出时更要留下模型当时回了什么，否则无从复盘。"""
    outcome, blob = _trace(monkeypatch, {"titles": ["  ", ""]}, tmp_path)
    assert "未产出有效标题" in outcome
    assert blob["raw"] == {"titles": ["  ", ""]}
    assert blob["accepted"] == 0
