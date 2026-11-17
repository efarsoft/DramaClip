"""整篇叙事试验线（W6）：锚定铺轴与解析/重掷行为钉。

铺轴三钉：锚定 quote 精确定位转写段（start/end 取自台词区间，LLM 不再产时间
戳）；无锚句沿用上一句集与光标续写（转场句跟随叙事流）；quote 失配走 difflib
模糊（≥0.55）。重掷一钉：硬审查不过带规则原句重掷。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.narration import flow_writer
from dramaclip.engines.semantic.llm_client import LlmUnavailable


def _episode_inputs() -> list[dict[str, Any]]:
    return [
        {
            "number": 1,
            "episode_id": "ep1",
            "duration": 60.0,
            "segments": [
                {"start": 0.0, "end": 4.0, "text": "她把丈夫的药倒进了老鼠洞"},
                {"start": 5.0, "end": 9.0, "text": "丈夫的病总不见好，是药里有人动了手脚"},
                {"start": 10.0, "end": 14.0, "text": "她照常烧水做饭，等着那人露出马脚"},
            ],
        },
        {
            "number": 2,
            "episode_id": "ep2",
            "duration": 50.0,
            "segments": [
                {"start": 0.0, "end": 5.0, "text": "那人终于登门，手里拎着两盒补品"},
            ],
        },
    ]


def _flow_json() -> str:
    return json.dumps(
        {
            "hook": {"quote": "她把丈夫的药倒进了老鼠洞", "text": "一碗药，毒死的不只是老鼠。"},
            "segments": [
                {"quote": "是药里有人动了手脚", "text": "她很快想明白了药的来历。"},
                {"quote": "", "text": "她不动声色地等着。"},
                {"quote": "那人终于登门", "text": "戏中人自己送上了门。"},
                {"quote": "她照常烧水做饭", "text": "收网的时辰到了。"},
            ],
            "cta": {"quote": "等着那人露出马脚", "text": "真相的反转，点左下角看全集。"},
        },
        ensure_ascii=False,
    )


class _FakeLlm:
    def __init__(self, payload: str) -> None:
        self._payload = payload
        self.calls = 0

    def chat_json(self, _system: str, _user: str, temperature: float = 0.3) -> Any:
        self.calls += 1
        if self.calls == 1:
            raise ValueError("mock: 第一轮硬审查不过")
        return json.loads(self._payload)


def test_anchor_maps_quote_to_transcript_window(tmp_path: Path) -> None:
    """锚定 quote 精确定位转写段：start/end 取自台词区间（LLM 不产时间戳）。"""
    llm = _FakeLlm(_flow_json())
    script = flow_writer.write_flow_script(
        llm,
        _episode_inputs(),
        project_name="测试剧",
        angle_block="",
        trace_path=tmp_path / "trace.json",
    )
    # hook 锚在 ep1 的 0-4s 段（hook 窗由 build 铺首窗）；segments[0] 是首个
    # body 句，锚 5-9 段——起点取锚段区间（LLM 不产时间戳）
    first = script.segments[0]
    assert first.episode == 1
    assert first.start == pytest.approx(5.0)
    assert first.end == pytest.approx(9.0)
    assert script.hook.startswith("一碗药")
    assert json.loads(json.dumps(script.model_dump()))  # 可落库


def test_unanchored_line_follows_previous_cursor(tmp_path: Path) -> None:
    """无锚句（quote 空串）：沿用上一句的集与光标续写（转场句跟随叙事流）。"""
    llm = _FakeLlm(_flow_json())
    script = flow_writer.write_flow_script(
        llm,
        _episode_inputs(),
        project_name="测试剧",
        angle_block="",
        trace_path=tmp_path / "trace.json",
    )
    # 第三个 body 句无锚：episode 沿用上一句（ep1）、起点接其窗尾
    unanchored = script.segments[1]
    assert unanchored.episode == 1
    assert unanchored.start >= script.segments[0].end - 0.01


def test_fuzzy_anchor_catches_close_paraphrase(tmp_path: Path) -> None:
    """quote 与台词高重叠（LLM 摘录带了标点差异）：difflib 模糊兜住。"""
    payload = json.dumps(
        {
            "hook": {"quote": "", "text": "开场。"},
            "segments": [
                {"quote": "她把丈夫的药,倒进了老鼠洞", "text": "锚定句。"},
                {"quote": "", "text": "后续。"},
                {"quote": "", "text": "再后续。"},
                {"quote": "", "text": "收尾。"},
            ],
            "cta": {"quote": "", "text": "引导。"},
        },
        ensure_ascii=False,
    )
    llm = _FakeLlm(payload)
    script = flow_writer.write_flow_script(
        llm,
        _episode_inputs(),
        project_name="测试剧",
        angle_block="",
        trace_path=tmp_path / "trace.json",
    )
    assert script.segments[0].episode == 1
    assert script.segments[0].start == pytest.approx(0.0)


def test_llm_unavailable_backoff_then_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(flow_writer.time, "sleep", lambda _s: None)
    llm = _FakeLlm(_flow_json())

    def _fail_then_ok(_s: str, _u: str, **_k: object) -> Any:
        llm.calls += 1
        if llm.calls == 1:
            raise LlmUnavailable("端点停顿")
        return json.loads(_flow_json())

    monkeypatch.setattr(llm, "chat_json", _fail_then_ok)
    # LlmUnavailable 在轮内被退避吞掉重试（与剧本链同款）；第 2 轮成功即正常返回
    script = flow_writer.write_flow_script(
        llm,
        _episode_inputs(),
        project_name="测试剧",
        angle_block="",
        trace_path=tmp_path / "trace.json",
    )
    assert llm.calls == 2
    assert script.segments
