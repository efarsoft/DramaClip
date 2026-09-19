"""跨集剧本编排：多集转写输入 → 带集号剧本 → 跨集时间轴。"""

from __future__ import annotations

from itertools import pairwise
from typing import Any

import pytest

from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.narration import scriptwriter
from dramaclip.engines.narration.models import StrategySpec
from dramaclip.engines.narration.pipeline import build_from_script_episodes


class FakeLLM:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    def chat_json(self, _system: str, user: str) -> Any:
        self.prompts.append(user)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def _payload() -> dict[str, Any]:
    return {
        "hook": "开场钩子",
        "segments": [
            {"episode": 1, "start": 1.0, "end": 10.0, "text": "第一集铺垫"},
            {"episode": 2, "start": 5.0, "end": 15.0, "text": "第二集反转"},
            {"episode": 9, "start": 1.0, "end": 8.0, "text": "不存在的集"},
        ],
        "cta": "点我看结局",
    }


_EPISODE_INPUTS = [
    {
        "number": 1,
        "duration": 100.0,
        "segments": [{"start": 1.0, "end": 10.0, "text": "第一集铺垫"}],
    },
    {
        "number": 2,
        "duration": 90.0,
        "segments": [{"start": 5.0, "end": 15.0, "text": "第二集反转"}],
    },
]


def test_write_script_episodes_multi() -> None:
    fake = FakeLLM(_payload())
    script = scriptwriter.write_script_episodes(
        fake, _EPISODE_INPUTS, target_min_s=30, target_max_s=120,
        angle_block="",
        project_name="剧"
    )
    episodes = [segment.episode for segment in script.segments]
    assert episodes == [1, 2]  # 未知集号（9）被丢弃
    assert "【第1集】" in fake.prompts[0] and "【第2集】" in fake.prompts[0]
    assert "跨集叙事要求" in fake.prompts[0]


def test_write_script_episodes_empty_transcript_raises() -> None:
    fake = FakeLLM(_payload())
    empty = [{"number": 1, "duration": 60.0, "segments": []}]
    with pytest.raises(ValueError, match="无米下锅"):
        scriptwriter.write_script_episodes(
            fake, empty, target_min_s=30, target_max_s=60,
            angle_block="",
            project_name="剧"
        )


def _asr(spans: list[tuple[float, float]]) -> list[AsrSegment]:
    return [
        AsrSegment(start=start, end=end, text=f"台词{index}")
        for index, (start, end) in enumerate(spans)
    ]


def test_build_from_script_episodes_spans_multiple_sources() -> None:
    script = scriptwriter.Script(
        hook="钩子",
        segments=[
            scriptwriter.ScriptSegment(episode=1, start=2.0, end=12.0, text="第一集解说"),
            scriptwriter.ScriptSegment(episode=2, start=3.0, end=13.0, text="第二集解说"),
        ],
        cta="点我看结局",
    )
    episode_map = {
        1: ("ep-a", _asr([(0.0, 20.0)])),
        2: ("ep-b", _asr([(0.0, 30.0)])),
    }
    durations = {1: 100.0, 2: 90.0}
    plan = build_from_script_episodes(episode_map, durations, script, StrategySpec())

    assert plan.planner == "llm_script"
    assert [seg.episode_id for seg in plan.timeline] == ["ep-a", "ep-a", "ep-b", "ep-b"]
    # 钩子挂第一段所在集；解说字幕与 narration_texts 一一对应
    assert plan.timeline[0].subtitle_text == "钩子"
    assert len(plan.narration_texts) == 4
    # 段→文案的 id 接线：剧本链的文案是成稿，故不能用 conftest.assert_slots_paired
    # （它还断言 `not text.text`）。少了这行，删掉钩子/正文/CTA 三处 narration_id= 全绿，
    # 而回填层只认 id——届时每条剧情解说方案都在配音期炸「编排自相矛盾」，模式等于死了。
    assert [seg.narration_id for seg in plan.timeline] == [t.id for t in plan.narration_texts]


def test_build_clamps_to_episode_duration() -> None:
    script = scriptwriter.Script(
        hook="钩子",
        segments=[
            scriptwriter.ScriptSegment(episode=2, start=80.0, end=120.0, text="解说一"),
            scriptwriter.ScriptSegment(episode=2, start=120.0, end=160.0, text="解说二"),
        ],
        cta="",
    )
    episode_map = {2: ("ep-b", _asr([(80.0, 120.0)]))}
    plan = build_from_script_episodes(episode_map, {2: 90.0}, script, StrategySpec())
    for segment in plan.timeline:
        assert segment.end <= 95.0  # 集时长 90s + 5s 容差内


def test_prompt_keeps_raw_segments_by_episode() -> None:
    """转写逐段原样提交（不合并）：每段一行「开始-结束 台词」，按集分组。"""
    fake = FakeLLM({
        "hook": "钩子",
        "segments": [
            {"episode": 1, "start": 0.0, "end": 1.0, "text": "解说一"},
            {"episode": 1, "start": 1.0, "end": 2.0, "text": "解说二"},
        ],
        "cta": "",
    })
    inputs = [
        {
            "number": 1,
            "duration": 60.0,
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "據最新消息"},
                {"start": 1.0, "end": 2.0, "text": "昨日發生在"},
                {"start": 2.0, "end": 4.0, "text": "京海大道的實車連撞"},
            ],
        }
    ]
    scriptwriter.write_script_episodes(
        fake, inputs, target_min_s=30, target_max_s=60,
            angle_block="",
            project_name="剧"
    )
    user = fake.prompts[0]
    assert "【第1集】" in user
    assert "00:00-00:01 據最新消息" in user
    assert "00:01-00:02 昨日發生在" in user
    assert "00:02-00:04 京海大道的實車連撞" in user


def test_near_adjacent_segments_bridge_without_stutter() -> None:
    """#3 跳帧修复（编排层）：同集近邻段（间隔 <1s）贴合为连续播放，消除微跳跃。

    转写区间**故意离剧本切点 1.5s 以上**：否则 `snap` 会自己把 6.03 吸附到 5.5，
    贴合与否都得到同一个 0 间隔，这条用例就变成永真——上一版正是栽在这里。
    回填那一层的同一不变量由 `test_backfill_timeline.py` 守。
    """
    script = scriptwriter.Script(
        hook="钩子",
        segments=[
            scriptwriter.ScriptSegment(
                episode=1, start=0.08, end=5.58, text="第一段解说文案超过时长"
            ),
            scriptwriter.ScriptSegment(
                episode=1, start=6.03, end=13.155, text="第二段解说文案也超过时长"
            ),
        ],
        cta="点我看结局",
    )
    episode_map = {1: ("ep-a", _asr([(0.0, 1.0)]))}
    durations = {1: 100.0}
    plan = build_from_script_episodes(episode_map, durations, script, StrategySpec())

    same_ep = [
        (round(seg.start, 2), round(seg.end, 2))
        for seg in plan.timeline
        if seg.episode_id == "ep-a"
    ]
    for (_prev_start, prev_end), (next_start, _next_end) in pairwise(same_ep):
        gap = round(next_start - prev_end, 2)
        assert gap == 0.0, f"近邻段出现 {gap}s 微跳跃（应为连续衔接）"
    # 6.03 没有被吸附、也没被留在原地：它被拉回上一段的结尾 5.58
    assert same_ep[2] == (5.58, 13.15), f"贴合落点不对：{same_ep[2]}"
