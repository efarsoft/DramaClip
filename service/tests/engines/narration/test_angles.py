"""angles.select_angles：K 条卖点互异的取材角度。

降级禁止（规格 §3.3.1）在此的具体形态是「不许凑数」：选题答不出 K 条互异角度时
必须抛，而不是拿重复的、缺字段的、越界集号的凑够 K 条交给下游——那样界面会显示
K 张卡，其中几张是同一部片换了个说法，正是 §4.3 要拦的老虎机。

**每一条拒绝分支都配了变异检查（Step 6）**：上一批实测抓到四条「分支删了测试照绿」
的用例，本文件不接受那种绿灯。
"""

from __future__ import annotations

from typing import Any

import pytest

from dramaclip.engines.narration import angles
from dramaclip.engines.semantic.llm_client import LlmUnavailable

_SETTINGS = {
    "llm.base_url": "http://llm.test/v1",
    "llm.api_key": "sk-test",
    "llm.model": "test-model",
    "_project_name": "透视眼",
    "_genre": "复仇",
}

# 三集，每集两段转写：够选题看出「这部剧有三条线」
_EPISODES: list[dict[str, Any]] = [
    {
        "number": number,
        "episode_id": f"ep{number}",
        "duration": 60.0,
        "segments": [
            {"start": 1.0, "end": 4.0, "text": f"第 {number} 集台词一"},
            {"start": 5.0, "end": 8.0, "text": f"第 {number} 集台词二"},
        ],
    }
    for number in (1, 2, 3)
]


class FakeLlm:
    """按队列应答 chat_json，记录每次 user prompt 供断言。"""

    calls: list[str] = []
    queue: list[Any] = []

    def __init__(self, _config: Any, timeout_s: float = 60.0) -> None:
        self.timeout_s = timeout_s

    def chat_json(self, _system: str, user: str, temperature: float = 0.3) -> Any:
        FakeLlm.calls.append(user)
        item = FakeLlm.queue.pop(0) if len(FakeLlm.queue) > 1 else FakeLlm.queue[0]
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture()
def llm(monkeypatch: pytest.MonkeyPatch) -> Any:
    FakeLlm.calls = []
    FakeLlm.queue = []
    monkeypatch.setattr(angles, "LlmClient", FakeLlm)
    return FakeLlm


def _angle(index: int, episode: int) -> dict[str, Any]:
    return {
        "name": f"角度{index}",
        "reason": f"第 {episode} 集这条线最狠",
        "hook": f"第 {episode} 集的开场钩子",
        "episode_numbers": [episode],
    }


def _payload(count: int = 3) -> dict[str, Any]:
    return {"angles": [_angle(i + 1, i + 1) for i in range(count)]}


def _select(**overrides: Any) -> list[angles.AngleBrief]:
    kwargs: dict[str, Any] = {
        "mode": "full_narration",
        "mode_label": "全片解说",
        "k": 3,
        "episode_inputs": _EPISODES,
        "settings": _SETTINGS,
        "excluded": [],
    }
    kwargs.update(overrides)
    return angles.select_angles(**kwargs)


def test_returns_k_distinct_briefs(llm: Any) -> None:
    llm.queue = [_payload()]
    briefs = _select()
    assert [brief.name for brief in briefs] == ["角度1", "角度2", "角度3"]
    assert [brief.episode_numbers for brief in briefs] == [[1], [2], [3]]
    assert all(brief.reason and brief.hook for brief in briefs)


def test_prompt_carries_mode_k_and_transcript(llm: Any) -> None:
    llm.queue = [_payload()]
    _select()
    prompt = FakeLlm.calls[0]
    assert "透视眼" in prompt and "全片解说" in prompt
    assert "需要 3 条卖点互异的取材角度" in prompt
    assert "第 1 集台词一" in prompt and "第 3 集台词二" in prompt, "跨集转写未进 prompt"
    assert "至少一个" in prompt, "「一条方案可以取多集」这条约束没交代给模型（规格 §1）"


def test_prompt_asks_for_an_episode_set(llm: Any) -> None:
    """规格 §1 的「跨集方案」：每条角度给出**全部**取材集，可以是一个也可以是多个。

    2026-09-12 裁决之后不再有"单集模式"这回事，故 `select_angles` 也没有 `cross_episode`
    这个形参了——留着它就是一个恒为 True 的开关，而开关的注释会作为一句关于代码的假话
    被提交（「其余模式的编排器一条片只吃一集」，裁决之后不成立）。
    """
    llm.queue = [{"angles": [dict(_angle(1, 1), episode_numbers=[1, 3])]}]
    briefs = _select(mode="dialogue_narration", mode_label="剧情解说", k=1)
    assert briefs[0].episode_numbers == [1, 3]
    assert "至少一个" in FakeLlm.calls[0]
    assert "恰好一个集号" not in FakeLlm.calls[0], "单集约束的措辞还留着"


def test_excluded_angles_are_listed_in_the_prompt(llm: Any) -> None:
    llm.queue = [_payload()]
    _select(excluded=["复仇线"])
    assert "已存在、不得重复的角度：复仇线" in FakeLlm.calls[0]


def test_unconfigured_llm_raises_before_prompt(llm: Any) -> None:
    settings = dict(_SETTINGS, **{"llm.model": ""})
    with pytest.raises(LlmUnavailable, match="引擎"):
        _select(settings=settings)
    assert FakeLlm.calls == [], "未配置就该在发请求之前拦住"


def test_no_transcript_raises(llm: Any) -> None:
    empty = [{"number": 1, "episode_id": "ep1", "duration": 60.0, "segments": []}]
    with pytest.raises(ValueError, match="无米下锅"):
        _select(episode_inputs=empty)


def test_no_episodes_raises(llm: Any) -> None:
    with pytest.raises(ValueError, match="没有带转写的已完成集"):
        _select(episode_inputs=[])


def test_k_below_one_raises(llm: Any) -> None:
    with pytest.raises(ValueError, match="k 必须"):
        _select(k=0)


def test_fewer_angles_than_k_raises(llm: Any) -> None:
    """只答出 2 条却要求 3 条：不许拿重复的补齐，也不许悄悄把 K 降成 2。"""
    llm.queue = [_payload(2), {"angles": []}]
    with pytest.raises(ValueError, match="只给出 2 条角度，要求 3 条"):
        _select()
    assert len(FakeLlm.calls) == 2, "应重试一次"


def test_duplicate_names_raise(llm: Any) -> None:
    llm.queue = [{"angles": [_angle(1, 1), _angle(1, 2), _angle(3, 3)]}, {"angles": []}]
    with pytest.raises(ValueError, match="角度名重复"):
        _select()


def test_excluded_name_reproposed_raises(llm: Any) -> None:
    payload = {"angles": [dict(_angle(1, 1), name="复仇线"), _angle(2, 2), _angle(3, 3)]}
    llm.queue = [payload, {"angles": []}]
    with pytest.raises(ValueError, match="已被排除"):
        _select(excluded=["复仇线"])


def test_empty_field_raises(llm: Any) -> None:
    payload = {"angles": [dict(_angle(1, 1), hook="  "), _angle(2, 2), _angle(3, 3)]}
    llm.queue = [payload, {"angles": []}]
    with pytest.raises(ValueError, match="不得为空"):
        _select()


def test_unknown_episode_number_raises(llm: Any) -> None:
    llm.queue = [{"angles": [_angle(1, 9), _angle(2, 2), _angle(3, 3)]}, {"angles": []}]
    with pytest.raises(ValueError, match="取材集不存在"):
        _select()


def test_empty_episode_list_raises(llm: Any) -> None:
    payload = {
        "angles": [dict(_angle(1, 1), episode_numbers=[]), _angle(2, 2), _angle(3, 3)]
    }
    llm.queue = [payload, {"angles": []}]
    with pytest.raises(ValueError, match="没有给出取材集"):
        _select()


def test_oversize_name_raises(llm: Any) -> None:
    payload = {"angles": [dict(_angle(1, 1), name="长" * 13), _angle(2, 2), _angle(3, 3)]}
    llm.queue = [payload, {"angles": []}]
    with pytest.raises(ValueError, match="超出长度上限"):
        _select()


def test_oversize_hook_raises(llm: Any) -> None:
    payload = {"angles": [dict(_angle(1, 1), hook="钩" * 41), _angle(2, 2), _angle(3, 3)]}
    llm.queue = [payload, {"angles": []}]
    with pytest.raises(ValueError, match="钩子超出长度上限"):
        _select()


def test_oversize_reason_raises(llm: Any) -> None:
    """三个长度上限里只有 reason 那条**原本没有用例**（R8）：删掉它的 raise 全套照绿。

    `match` 必须写「理由超出长度上限」这个词：`_MAX_NAME_CHARS` 与 `_MAX_HOOK_CHARS`
    的两条消息分别是「角度名超出长度上限」与「钩子超出长度上限」，
    写"超出长度上限"会让三条分支互相顶包，红的时候不知道红的是哪条。
    """
    payload = {"angles": [dict(_angle(1, 1), reason="理" * 61), _angle(2, 2), _angle(3, 3)]}
    llm.queue = [payload, {"angles": []}]
    with pytest.raises(ValueError, match="理由超出长度上限"):
        _select()


def test_missing_angles_array_raises(llm: Any) -> None:
    llm.queue = [{"nope": 1}, {"angles": []}]
    with pytest.raises(ValueError, match="未返回 angles 数组"):
        _select()


def test_non_object_item_raises(llm: Any) -> None:
    llm.queue = [{"angles": ["一条字符串", _angle(2, 2), _angle(3, 3)]}, {"angles": []}]
    with pytest.raises(ValueError, match="非对象项"):
        _select()


def test_malformed_field_type_raises(llm: Any) -> None:
    payload = {
        "angles": [dict(_angle(1, 1), episode_numbers="第一集"), _angle(2, 2), _angle(3, 3)]
    }
    llm.queue = [payload, {"angles": []}]
    with pytest.raises(ValueError, match="字段不合法"):
        _select()


def test_extra_angles_are_cut_to_k_not_rejected(llm: Any) -> None:
    """多答不是质量问题：K 是用户的旋钮，取前 K 条即可（与「少答」完全不同，少答必抛）。"""
    llm.queue = [_payload(5)]
    assert len(_select()) == 3


def test_gateway_failure_retries_then_raises(llm: Any) -> None:
    llm.queue = [LlmUnavailable("网关 502"), {"angles": []}]
    with pytest.raises(ValueError, match="未产出 3 条合格角度"):
        _select()
    assert len(FakeLlm.calls) == 2


def test_prompt_block_names_the_selling_point(llm: Any) -> None:
    """成稿 prompt 的角度块：三要素齐备，且措辞由本模块独家持有（两条成稿链共用）。"""
    brief = angles.AngleBrief(
        name="复仇线", reason="第 3 集反杀最狠", hook="他跪着进了门", episode_numbers=[3]
    )
    block = angles.prompt_block(brief)
    assert "复仇线" in block and "第 3 集反杀最狠" in block and "他跪着进了门" in block
