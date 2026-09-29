"""跨集编剧：LLM 输出清洗、逐集裁剪、重试与失败即抛。"""

from __future__ import annotations

import json
from typing import Any

import pytest

from dramaclip.engines.narration import scriptwriter
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
        self.systems: list[str] = []
        self.users: list[str] = []

    def chat_json(self, system: str, user: str) -> dict[str, Any]:
        # 单元素脚本视为"每次都返回该结果"（write_script_episodes 内部会重试一次）
        self.calls += 1
        self.systems.append(system)
        self.users.append(user)
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return item


def _run(llm: FakeLLM) -> Script:
    return write_script_episodes(
        llm,
        _EPISODES,
        project_name="测试剧",
        angle_block="",
    min_segments=2,
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
            project_name="测试剧",
        angle_block="",
        min_segments=2,
        )



def _system_sent(**prompts: str) -> str:
    llm = FakeLLM([dict(_VALID_PAYLOAD)])
    write_script_episodes(
        llm, _EPISODES, project_name="测试剧", angle_block="", prompts=prompts,
    min_segments=2,
    )

    return llm.systems[0]


def _user_sent(**prompts: str) -> str:
    llm = FakeLLM([dict(_VALID_PAYLOAD)])
    write_script_episodes(
        llm, _EPISODES, project_name="测试剧", angle_block="", prompts=prompts,
    min_segments=2,
    )

    return llm.users[0]


def test_system_carries_the_rules_the_sanitizer_enforces() -> None:
    """清洗层会整段丢掉重叠与越界的片段：规则不写进提示词，等于让模型盲写再默默吃掉。

    实测 n=8（真机 2 集 116 行）：103 段原始输出里 59 段漏了 episode（旧版格式示例
    本身就没这个字段），18 段的 start 越过第一集真实长度（最远写到 446s），
    清洗层最终丢弃 42 段——全被当成第一集的重叠段吃掉。
    """
    system = _system_sent()
    assert '"episode": 集号整数' in system, "格式示例漏掉 episode，模型照抄就缺字段"
    assert "下一段的 start 不得早于前一段的 end" in system
    assert "本集台词截至" in system, "未把清洗层的时间上界告诉模型"


def test_user_block_points_at_the_band_instead_of_canceling_it() -> None:
    """同输入的自然实验：相隔 10 分钟的两次跑，「段数不设上限」措辞出 6 段，
    「正文 12-28 段」出更完整的冲突链。user 层再讲一遍「不设上限/由剧情需要决定」
    正好抵消掉 system 的段数区间。
    """
    user = _user_sent()
    assert "段数由剧情需要决定" not in user
    assert "段数区间" in user



def test_default_system_carries_both_layers() -> None:
    system = _system_sent()
    assert "【解说基本功——逐条强制遵守】" in system
    assert "正文 12-28 段" in system


def test_structure_override_replaces_only_the_structure() -> None:
    """换掉结构指令不该把基本功层一起带走：两层各自独立才可分别调。"""
    system = _system_sent(**{"prompt.scriptwriter_system": "只回 JSON。"})
    assert system.startswith("只回 JSON。")
    assert "正文 12-28 段" not in system
    assert "【解说基本功——逐条强制遵守】" in system


def test_floor_override_replaces_the_floor() -> None:
    """改基本功层必须真的换掉底线，而不是只换个标题、原文照旧跟在后面。"""
    system = _system_sent(
        **{"prompt.scriptwriter_fundamentals": "【解说基本功——逐条强制遵守】\n只准写短句。"}
    )
    assert "只准写短句。" in system
    assert "悬念管理" not in system


def test_saving_the_default_floor_verbatim_does_not_duplicate_it() -> None:
    """界面上「原样存回默认」是最常见的误操作：正文重复会让模型看到两份互相矛盾的底线。"""
    system = _system_sent(**{"prompt.scriptwriter_fundamentals": scriptwriter.FUNDAMENTALS})
    for token in ("【解说基本功——逐条强制遵守】", "人称二选一", "悬念管理"):
        assert system.count(token) == 1, token


def test_missing_episode_is_not_guessed_as_episode_one() -> None:
    """实测旧版 103 段里 59 段漏 episode，`episode: int = 1` 把第二集的段落悄悄塞回第一集：
    时间轴被钳到 192s 以内、后段整批判为重叠丢掉。多集输入下缺集号只能算不合格，不能猜。
    """
    payload = {
        "hook": "开场钩子",
        "segments": [
            {"episode": 1, "start": 1.0, "end": 10.0, "text": "第一段解说"},
            {"start": 5.0, "end": 15.0, "text": "漏了集号的第二段"},
        ],
        "cta": "点我看完结",
    }
    llm = FakeLLM([payload])
    with pytest.raises(ValueError, match="缺 episode"):
        _run(llm)
    assert llm.calls == 3, "不合格必须重试到上限（首次+2 次重试），一次不中就放弃等于白丢一遍"


def test_single_episode_may_omit_the_episode_field() -> None:
    """只有一集时集号没有歧义，不该为了格式洁癖把能用的剧本判死。"""
    payload = {
        "hook": "开场钩子",
        "segments": [
            {"start": 1.0, "end": 10.0, "text": "第一段解说"},
            {"start": 10.0, "end": 20.0, "text": "第二段解说"},
        ],
        "cta": "",
    }
    script = write_script_episodes(
        FakeLLM([payload]),
        [_EPISODES[0]],
        project_name="测试剧",
        angle_block="",
    min_segments=2,
    )

    assert [segment.episode for segment in script.segments] == [1, 1]


def test_trace_dumps_the_system_actually_sent(tmp_path) -> None:
    """留痕写默认值＝排查时看到的是假账：改了提示词却仍显示原生版本。"""
    llm = FakeLLM([dict(_VALID_PAYLOAD)])
    trace = tmp_path / "llm_script.json"
    write_script_episodes(
        llm, _EPISODES,
        project_name="测试剧",
        angle_block="",
        prompts={"prompt.scriptwriter_system": "只回 JSON。"},
        trace_path=trace,
    min_segments=2,
    )

    payload = json.loads(trace.read_text(encoding="utf-8"))
    assert payload["system"] == llm.systems[0]
    assert payload["system"].startswith("只回 JSON。")
    assert payload["user"] == llm.users[0]


# ------------------------------------------------------------- 清洗丢弃数可见化
# 实测真机剧本里清洗层吃掉 22-23% 的片段（未知集号、越界、重叠、空文案），
# 界面上一个数字都不见——方案看起来"就是这么长"。先做到可对账，不加硬门。

_DIRTY_PAYLOAD: dict[str, Any] = {
    "hook": "开场钩子",
    "segments": [
        {"episode": 1, "start": 1.0, "end": 10.0, "text": "第一段解说"},
        {"episode": 1, "start": 10.0, "end": 20.0, "text": "第二段解说"},
        {"episode": 2, "start": 5.0, "end": 15.0, "text": "第三段解说"},
        {"episode": 9, "start": 1.0, "end": 8.0, "text": "不存在的第九集"},
        {"episode": 1, "start": 20.0, "end": 30.0, "text": "   "},
    ],
    "cta": "点我看完结",
}


def test_clean_script_reports_no_drop() -> None:
    assert _run(FakeLLM([dict(_VALID_PAYLOAD)])).dropped_segments == 0


def test_sanitizer_drop_count_travels_with_the_script() -> None:
    """5 段进、3 段出：丢掉的 2 段（未知集号 + 空文案）必须是剧本上的一个数。"""
    script = _run(FakeLLM([dict(_DIRTY_PAYLOAD)]))
    assert [segment.text for segment in script.segments] == [
        "第一段解说", "第二段解说", "第三段解说",
    ]
    assert script.dropped_segments == 2


def test_drop_count_is_in_the_trace_too(tmp_path) -> None:
    trace = tmp_path / "llm_script.json"
    write_script_episodes(
        FakeLLM([dict(_DIRTY_PAYLOAD)]),
        _EPISODES,
        project_name="测试剧",
        angle_block="",
        trace_path=trace,
    min_segments=2,
    )

    attempt = json.loads(trace.read_text(encoding="utf-8"))["attempts"][-1]
    assert attempt["segments_kept"] == 3
    assert attempt["segments_dropped"] == 2


# ------------------------------------------------------------- 输出防御闭环（批次一 A2）
# 参考项目调研：NarratoAI/autoclip 都有「钳制到边界 + 重试注入格式强化 + 坏响应留痕」，
# 我们只有 pydantic 结构校验——LLM 幻觉时间戳只能等渲染期暴雷。


def test_negative_start_is_clamped_to_zero() -> None:
    """LLM 写出负数 start 是幻觉不是意图：钳到 0 保住这段，而不是留给渲染层去炸。"""
    payload = dict(
        _VALID_PAYLOAD,
        segments=[
            {"episode": 1, "start": -5.0, "end": 10.0, "text": "负起点段"},
            {"episode": 1, "start": 10.0, "end": 20.0, "text": "第二段解说"},
        ],
    )
    script = _run(FakeLLM([payload]))
    assert script.segments[0].start == 0.0
    assert len(script.segments) == 2


def test_unknown_episode_duration_does_not_drop_everything() -> None:
    """集时长缺失（0）等于没有上界可钳：钳到 0 会把整批段落静默丢光，剧本直接判死。"""
    episodes = [
        {
            "number": 1,
            "duration": 0.0,
            "segments": [
                {"start": 1.0, "end": 10.0, "text": "台词一"},
                {"start": 10.0, "end": 20.0, "text": "台词二"},
            ],
        }
    ]
    payload = {
        "hook": "开场钩子",
        "segments": [
            {"episode": 1, "start": 1.0, "end": 10.0, "text": "第一段解说"},
            {"episode": 1, "start": 10.0, "end": 20.0, "text": "第二段解说"},
        ],
        "cta": "",
    }
    script = write_script_episodes(
        FakeLLM([payload]), episodes, project_name="测试剧", angle_block="",
    min_segments=2,
    )

    assert [(segment.start, segment.end) for segment in script.segments] == [
        (1.0, 10.0),
        (10.0, 20.0),
    ]


def test_retry_cap_is_three_attempts() -> None:
    """首次 + 最多 2 次重试：只试一次就把「网关抖一下」当成「模型写不出」。"""
    llm = FakeLLM([ValueError("非法 JSON")])
    with pytest.raises(ValueError, match="未产出合法剧本"):
        _run(llm)
    assert llm.calls == 3


def test_retry_prompt_appends_format_reinforcement() -> None:
    """重试不能原样重问：不追加格式强化指令，模型大概率原样再犯一遍。"""
    llm = FakeLLM([ValueError("非法 JSON"), dict(_VALID_PAYLOAD)])
    _run(llm)
    assert "格式强化" not in llm.users[0], "首次提问不该带强化指令"
    assert llm.users[1].startswith(llm.users[0]), "强化指令追加在原 prompt 末尾"
    assert "格式强化" in llm.users[1]
    assert "只输出 JSON" in llm.users[1]


def test_bad_raw_response_is_kept_in_trace(tmp_path) -> None:
    """结构校验失败时坏响应原文必须留痕：只记异常文案，排查时分不清模型到底写了什么。"""
    payload = dict(_VALID_PAYLOAD, hook="")  # min_length=1 → ValidationError
    trace = tmp_path / "llm_script.json"
    with pytest.raises(ValueError, match="未产出合法剧本"):
        write_script_episodes(
            FakeLLM([payload]),
            _EPISODES,
            project_name="测试剧",
            angle_block="",
            trace_path=trace,
        min_segments=2,
        )

    attempts = json.loads(trace.read_text(encoding="utf-8"))["attempts"]
    assert attempts[0]["raw"] == payload, "坏响应原文没进留痕"
    assert attempts[0]["error"].startswith("ValidationError")


def test_clamped_segments_are_counted_in_trace(tmp_path) -> None:
    """钳制是悄悄改数：留痕里必须能对上账，否则「剧本变短了」无从解释。"""
    payload = dict(
        _VALID_PAYLOAD,
        segments=[
            {"episode": 1, "start": 1.0, "end": 10.0, "text": "正文一"},
            {"episode": 1, "start": 10.0, "end": 20.0, "text": "正文二"},
            {"episode": 1, "start": 30.0, "end": 99.0, "text": "越界段（尾部钳到 40s）"},
        ],
    )
    trace = tmp_path / "llm_script.json"
    write_script_episodes(
        FakeLLM([payload]),
        _EPISODES,
        project_name="测试剧",
        angle_block="",
        trace_path=trace,
    min_segments=2,
    )

    attempt = json.loads(trace.read_text(encoding="utf-8"))["attempts"][-1]
    assert attempt["segments_clamped"] == 1
