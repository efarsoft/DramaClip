"""跨集编剧：LLM 输出清洗、逐集裁剪、重试与失败即抛。"""

from __future__ import annotations

from typing import Any

import pytest

from dramaclip.engines.narration.scriptwriter import Script, write_script_episodes

_VALID_PAYLOAD: dict[str, Any] = {
    "hook": "开场钩子",
    "segments": [
        {"episode": 1, "start": 1.0, "end": 10.0, "text": "第一段解说"},
        {"episode": 1, "start": 10.0, "end": 20.0, "text": "第二段解说"},
        {"episode": 2, "start": 5.0, "end": 15.0, "text": "第三段解说"},
    ],
    "cta": "点我看完结",
}

_EPISODES: list[dict[str, Any]] = [
    {
        "number": 1,
        "duration": 40.0,
        "segments": [
            {"start": 1.0, "end": 10.0, "text": "台词一"},
            {"start": 10.0, "end": 40.0, "text": "台词二"},
        ],
    },
    {
        "number": 2,
        "duration": 60.0,
        "segments": [{"start": 5.0, "end": 20.0, "text": "台词三"}],
    },
]


class FakeLLM:
    """按脚本返回/抛出，模拟 LLM 行为。"""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls = 0

    def chat_json(self, _system: str, _user: str) -> dict[str, Any]:
        # 单元素脚本视为"每次都返回该结果"（write_script_episodes 内部会重试一次）
        self.calls += 1
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return item


def _run(llm: FakeLLM) -> Script:
    return write_script_episodes(
        llm,
        _EPISODES,
        target_min_s=30,
        target_max_s=300,
        project_name="测试剧",
    )


def test_valid_payload_returns_sanitized_script() -> None:
    llm = FakeLLM([dict(_VALID_PAYLOAD)])
    script = _run(llm)
    assert [segment.text for segment in script.segments] == [
        "第一段解说",
        "第二段解说",
        "第三段解说",
    ]
    assert [segment.episode for segment in script.segments] == [1, 1, 2]
    assert script.hook == "开场钩子" and script.cta == "点我看完结"
    assert llm.calls == 1


def test_segments_sorted_and_overlaps_trimmed_per_episode() -> None:
    payload = dict(
        _VALID_PAYLOAD,
        segments=[
            {"episode": 1, "start": 20.0, "end": 30.0, "text": "乱序段"},
            {"episode": 1, "start": 1.0, "end": 22.0, "text": "覆盖段"},
            {"episode": 1, "start": 25.0, "end": 30.0, "text": "重叠裁剪"},
            {"episode": 2, "start": 8.0, "end": 15.0, "text": "另一集不受第一集游标影响"},
        ],
    )
    script = _run(FakeLLM([payload]))
    ep1 = [segment for segment in script.segments if segment.episode == 1]
    starts = [segment.start for segment in ep1]
    assert starts == sorted(starts), "同集内乱序段被排序"
    for first, second in zip(ep1, ep1[1:], strict=False):
        assert first.end <= second.start + 0.01, "重叠被逐集游标裁剪"
    assert script.segments[-1].episode == 2


def test_out_of_bounds_clamped_to_episode_duration() -> None:
    payload = dict(
        _VALID_PAYLOAD,
        segments=[
            {"episode": 1, "start": 1.0, "end": 10.0, "text": "正文一"},
            {"episode": 1, "start": 10.0, "end": 20.0, "text": "正文二"},
            {"episode": 1, "start": 30.0, "end": 99.0, "text": "越界段（尾部被裁到 40s）"},
        ],
    )
    script = _run(FakeLLM([payload]))
    assert len(script.segments) == 3, "未越界段原样保留"
    assert max(segment.end for segment in script.segments) <= 40.0


def test_invalid_json_raises() -> None:
    with pytest.raises(ValueError, match="未产出合法剧本"):
        _run(FakeLLM([ValueError("非法 JSON")]))


def test_too_few_segments_raises() -> None:
    """清洗后不足 `_MIN_SEGMENTS` 段：越界集号被丢光，等同没写。"""
    payload = dict(
        _VALID_PAYLOAD,
        segments=[{"episode": 9, "start": 1.0, "end": 10.0, "text": "集号不存在"}],
    )
    with pytest.raises(ValueError, match="未产出合法剧本"):
        _run(FakeLLM([payload]))


def test_retries_once_before_raising() -> None:
    llm = FakeLLM([ValueError("第一次失败"), dict(_VALID_PAYLOAD)])
    _run(llm)
    assert llm.calls == 2, "第一次失败必须重问一次"


@pytest.mark.parametrize(
    "payload",
    [
        {"hook": "", "segments": _VALID_PAYLOAD["segments"]},
        {"hook": "x", "segments": [{"episode": 1, "start": "abc", "end": 2, "text": "t"}] * 3},
        {"segments": [{"episode": 1, "start": 1.0, "end": 2.0, "text": "无钩子"}]},
    ],
)
def test_malformed_payloads_raise(payload: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="未产出合法剧本"):
        _run(FakeLLM([payload]))


def test_no_transcript_raises() -> None:
    """所有集都没有转写：无米下锅要直说，不能返回 None 让上层以为是自己降级了。"""
    empty = [{"number": 1, "duration": 40.0, "segments": []}]
    with pytest.raises(ValueError, match="无米下锅"):
        write_script_episodes(
            FakeLLM([dict(_VALID_PAYLOAD)]), empty,
            target_min_s=30, target_max_s=300, project_name="测试剧",
        )
