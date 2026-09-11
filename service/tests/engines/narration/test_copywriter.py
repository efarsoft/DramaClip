"""narration.copywriter：槽位 → LLM → 文案。降级禁止，故所有失败路径都必须是异常。"""

from __future__ import annotations

import json
from pathlib import Path
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

# Task 4 传的是 pipeline 的模式标签表；这里用一个真标签，不传空串糊过去
_MODE_LABEL = "全片解说"

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
    plan = copywriter.write_plan_copy(_plan(), _SEGMENTS, _SETTINGS, mode_label=_MODE_LABEL)
    assert plan.planner == "llm_script"
    assert [t.text for t in plan.narration_texts] == [
        "第 1 条解说", "第 2 条解说", "第 3 条解说", "第 4 条解说"
    ]


def test_prompt_carries_slot_brief_and_local_transcript(llm: Any) -> None:
    """台词必须按槽位各自的画面区间分发——只在 prompt 里"出现过"等于没验。"""
    llm.queue = [_lines()]
    copywriter.write_plan_copy(_plan(), _SEGMENTS, _SETTINGS, mode_label=_MODE_LABEL)
    prompt = llm.calls[0]
    assert "透视眼" in prompt and "复仇" in prompt
    assert "强节奏" in prompt, "口味层指令未注入"
    assert "模式：全片解说" in prompt, "模式标签未进 prompt"
    block = prompt.split("[full-2]")[1].split("[full-3]")[0]
    assert "要做的事：" in block and "高潮" in block, "槽位职责未随本槽进 prompt"
    assert "画面区间：12.0-22.0s" in block, "区间必须取自配对画面段"
    assert "第 1 幕的原话" in block, "台词必须落在自己区间的槽位下"
    assert "第 0 幕的原话" not in block and "第 2 幕的原话" not in block, "槽位之间不许串台词"


def test_slot_without_transcript_forbids_invention(llm: Any) -> None:
    """无转写可依据时（该区间一句台词没有）必须明写"不得编造"：每个槽位都得看到这句。"""
    llm.queue = [_lines()]
    copywriter.write_plan_copy(_plan(), [], _SETTINGS, mode_label=_MODE_LABEL)
    prompt = llm.calls[0]
    assert prompt.count("（该区间无台词转写") == len(_SCENES), "每个空区间槽位都要有禁止编造的提示"


def test_missing_slot_raises(llm: Any) -> None:
    llm.queue = [{"lines": [{"id": "full-1", "text": "只写了一条"}]}]
    with pytest.raises(ValueError, match="漏了 3 个槽位"):
        copywriter.write_plan_copy(_plan(), _SEGMENTS, _SETTINGS, mode_label=_MODE_LABEL)


def test_retries_once_then_raises(llm: Any) -> None:
    llm.queue = [LlmUnavailable("网关 502"), {"lines": []}]
    with pytest.raises(ValueError, match="网关 502") as excinfo:
        copywriter.write_plan_copy(_plan(), _SEGMENTS, _SETTINGS, mode_label=_MODE_LABEL)
    assert len(llm.calls) == 2, "应重试一次"
    # 槽位 id 只出现在漏答详情里一次：包装语再列一遍等于给队列页刷屏
    assert str(excinfo.value) == (
        "编剧未产出合格文案：LlmUnavailable: 网关 502；"
        "ValueError: 编剧漏了 4 个槽位：full-1, full-2, full-3, full-4"
    )


def test_unconfigured_llm_raises_before_prompt(llm: Any) -> None:
    settings = dict(_SETTINGS)
    settings["llm.model"] = ""
    with pytest.raises(LlmUnavailable, match="文案必须由编剧模型产出"):
        copywriter.write_plan_copy(_plan(), _SEGMENTS, settings, mode_label=_MODE_LABEL)
    assert llm.calls == []


def test_oversize_line_rejected(llm: Any) -> None:
    """超出 60 字 ×1.2 容忍即判没答：重试一次仍超长就抛，不得把长句塞进成片。"""
    over = "长" * 80
    llm.queue = [
        {"lines": [{"id": f"full-{i + 1}", "text": over} for i in range(len(_SCENES))]}
    ]
    with pytest.raises(ValueError, match="未产出合格文案"):
        copywriter.write_plan_copy(_plan(), _SEGMENTS, _SETTINGS, mode_label=_MODE_LABEL)
    assert len(llm.calls) == 2, "超长应触发一次重问"


def test_unknown_ids_never_count_as_answers(llm: Any) -> None:
    """模型自己造 id 等于一条没答：不按位置凑数，也不让野生日 id 拿到校验资格。

    四条 id 全不在 plan 里，其中一条还超长——若未知 id 逃不过长度校验，说明
    `key not in wanted` 的丢弃分支没了：报错会被那条不存在的槽位劫持，
    而真正该说的是「我们问的 4 个槽位一个都没回」。
    """
    llm.queue = [{"lines": [
        {"id": "full-9", "text": "模型自造的槽位" + "长" * 80},
        {"id": "full-0", "text": "还是自造的"},
        {"id": "intro-2", "text": "这轮回的压根不是 full_narration 的 id"},
        {"id": "dual-1", "text": "第四条也是"},
    ]}]
    with pytest.raises(ValueError, match="漏了 4 个槽位") as excinfo:
        copywriter.write_plan_copy(_plan(), _SEGMENTS, _SETTINGS, mode_label=_MODE_LABEL)
    message = str(excinfo.value)
    assert "full-1, full-2, full-3, full-4" in message, "报错须点名我们要的槽位"
    assert "full-9" not in message, "未知 id 应被静默丢弃，不该出现在报错里"
    assert len(llm.calls) == 2, "答非所问同样要重问一次"


def test_empty_answer_counts_as_no_answer(llm: Any) -> None:
    """某槽位交白卷就是没交：漏答报错必须点名它，绝不能把空串当解说填进成片。"""
    blanked = _lines()
    blanked["lines"][1]["text"] = ""
    llm.queue = [blanked]
    with pytest.raises(ValueError, match="漏了 1 个槽位") as excinfo:
        copywriter.write_plan_copy(_plan(), _SEGMENTS, _SETTINGS, mode_label=_MODE_LABEL)
    assert "full-2" in str(excinfo.value)
    assert len(llm.calls) == 2, "空答同样要重问一次"


def test_trace_lands_on_the_raise_path(llm: Any, tmp_path: Path) -> None:
    """抛异常也必须留痕：那个文件是唯一能事后审计「模型到底被问了什么」的证据。"""
    llm.queue = [{"lines": [{"id": "full-1", "text": "只回了一条"}]}]
    with pytest.raises(ValueError, match="漏了 3 个槽位"):
        copywriter.write_plan_copy(
            _plan(), _SEGMENTS, _SETTINGS, mode_label=_MODE_LABEL, trace_dir=tmp_path
        )
    traces = list(tmp_path.glob("llm_copy_full_narration_*.json"))
    assert len(traces) == 1, f"失败路径同样要落盘，实得 {traces}"
    payload = json.loads(traces[0].read_text(encoding="utf-8"))
    assert "full-2" in payload["attempts"][0]["error"], "留痕要点名漏答的槽位"
    assert "画面区间" in payload["user"], "留痕要能还原模型实际看到的区间"


def test_slot_without_paired_segment_raises(llm: Any) -> None:
    """槽位没有配对画面段＝编排器漏写 narration_id：抛，绝不退化成"没有区间的槽位"瞎写。"""
    stripped = _plan()
    plan = stripped.model_copy(update={
        "timeline": [
            segment.model_copy(update={"narration_id": None}) for segment in stripped.timeline
        ]
    })
    llm.queue = [_lines()]  # 就算真去问网关，答案也是齐的：红线只能来自"压根不该问"
    with pytest.raises(ValueError, match="full-1 没有配对画面段"):
        copywriter.write_plan_copy(plan, _SEGMENTS, _SETTINGS, mode_label=_MODE_LABEL)
    assert llm.calls == [], "prompt 都拼不出来，不该浪费一次网关调用"
