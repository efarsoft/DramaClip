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
