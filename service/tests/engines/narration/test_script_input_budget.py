"""跨集剧本输入：预算内必须让每一集都有代表，不得按集号头部截断。"""

from __future__ import annotations

import re

from dramaclip.engines.narration import scriptwriter


def _ep(number: int, segs: int) -> dict:
    return {
        "number": number,
        "episode_id": f"e{number}",
        "duration": 160.0,
        "segments": [
            {"start": float(i), "end": float(i) + 1, "text": f"集{number}台词{i}"}
            for i in range(segs)
        ],
    }


def test_all_episodes_are_represented() -> None:
    """80 集 × 60 段 = 4800 行，远超 500 预算：旧实现只喂进前 ~10 集。"""
    inputs = [_ep(n, 60) for n in range(1, 81)]
    prompt = scriptwriter.format_transcript_episodes(inputs)
    for number in (1, 20, 40, 60, 80):
        assert f"【第{number}集】" in prompt, f"第{number}集被静默整集丢弃"
        assert f"集{number}台词" in prompt


def test_truncation_is_reported() -> None:
    prompt = scriptwriter.format_transcript_episodes([_ep(n, 60) for n in range(1, 81)])
    assert "摘录" in prompt, "未向模型说明看到的是配额摘录而非全量逐字"


def test_no_empty_episode_header() -> None:
    """一集若最终一行都没进，就不得留下孤立的集标题。"""
    prompt = scriptwriter.format_transcript_episodes([_ep(n, 60) for n in range(1, 81)])
    headers = re.findall(r"【第(\d+)集】\n([^\n]*)", prompt)
    assert headers, "未匹配到任何集块——标题格式与预期不符"
    for number, following in headers:
        assert following.strip(), f"第{number}集标题后为空"


def test_episode_tail_is_sampled_not_skipped() -> None:
    """单集内必须取到尾部——短剧高潮常在集尾，只取开头等于丢掉钩子。"""
    prompt = scriptwriter.format_transcript_episodes([_ep(1, 60), _ep(2, 60)])
    assert "集1台词59" in prompt


def test_small_project_uses_every_line() -> None:
    """集数少时不应无谓丢行：3 集 × 20 段 = 60 行，远在预算内。"""
    prompt = scriptwriter.format_transcript_episodes([_ep(n, 20) for n in (1, 2, 3)])
    assert prompt.count("台词19") == 3


def test_each_episode_states_its_time_bounds() -> None:
    """实测：模型见不到集长就编越界时间戳（单次 20 段里 16 段越过集尾），
    清洗层再把这些段整段吃掉。每集标题下必须交代可用时间上界。
    """
    prompt = scriptwriter.format_transcript_episodes([_ep(1, 20)])
    assert "本集台词截至 00:20" in prompt, "未告知模型该集台词的可用上界"
    assert "全长 02:40" in prompt, "未告知模型该集真实时长"


def test_unknown_duration_does_not_fabricate_a_length() -> None:
    """集长缺失时只能说台词截至，不能凭空报一个 00:00 的全长。"""
    ep = _ep(1, 5)
    ep.pop("duration")
    prompt = scriptwriter.format_transcript_episodes([ep])
    assert "本集台词截至 00:05" in prompt
    assert "全长" not in prompt


def test_speaker_label_rendered_when_present() -> None:
    """说话人分离开启时，台词行带聚类标签前缀——真名化是编剧 LLM 的活。"""
    ep = _ep(1, 2)
    ep["segments"][0]["speaker"] = "角色A"
    prompt = scriptwriter.format_transcript_episodes([ep])
    assert "[角色A] 集1台词0" in prompt
    assert "集1台词1" in prompt
    assert "[角色A] 集1台词1" not in prompt, "没标签的行不编造归属"


def test_speaker_absent_keeps_bare_lines() -> None:
    """分离未开启（或字段为空）：转写行保持原样，不出空括号。"""
    ep = _ep(1, 2)
    ep["segments"][0]["speaker"] = None
    prompt = scriptwriter.format_transcript_episodes([ep])
    assert "00:00-00:01 集1台词0" in prompt
    assert "[]" not in prompt and "[None]" not in prompt

