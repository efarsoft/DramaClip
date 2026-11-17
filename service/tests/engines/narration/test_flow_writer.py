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


class _AlwaysOkLlm:
    """每轮都产出同一份合法稿（评审层单独打桩，生成层零干扰）。"""

    def __init__(self, payload: str) -> None:
        self._payload = payload
        self.prompts: list[str] = []

    def chat_json(self, _system: str, user: str, temperature: float = 0.3) -> Any:
        self.prompts.append(user)
        return json.loads(self._payload)


def test_flow_prompt_carries_hook_forms_and_rhythm_hint() -> None:
    """W7-1：system 带钩子四形态库、user 带每秒约四字的节奏参考（正向指导）。"""
    system, user = flow_writer.build_flow_request(
        _episode_inputs(),
        project_name="测试剧",
        angle_block="",
    )
    assert "结局前置" in system and "反常识断言" in system
    assert "绝境点名" in system and "诡异疑问" in system
    assert "每秒约四个字" in user
    assert "参考不是硬性上限" in user


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


def _write_with_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    llm: _AlwaysOkLlm,
    score_one: Any,
) -> Any:
    monkeypatch.setattr(flow_writer.variant_scoring, "score_one", score_one)
    return flow_writer.write_flow_script(
        llm,
        _episode_inputs(),
        project_name="测试剧",
        angle_block="",
        trace_path=tmp_path / "trace.json",
        settings={"llm.model": "stub"},
    )


def test_judge_low_score_feeds_suggestion_into_reroll(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W7-2：评审总分过低 → 拒稿一次，评审建议原文进下一轮 ask（软反馈）。"""
    llm = _AlwaysOkLlm(_flow_json())
    verdicts = iter(
        [
            {"total": 4.5, "suggestion": "把身份反差提到第一句"},
            {"total": 8.2, "suggestion": "已经是好稿"},
        ]
    )

    def _score_one(plan_data: Any, _angle: str, _settings: Any, **_k: object) -> Any:
        assert plan_data["narration_texts"], "评审喂进来的必须是解说全文"
        return next(verdicts)

    script = _write_with_settings(tmp_path, monkeypatch, llm, _score_one)
    assert script.segments
    assert "上一稿按这些意见重写" not in llm.prompts[0]
    assert "把身份反差提到第一句" in llm.prompts[1]


def test_judge_failure_skips_silently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """评审失败返 None：一轮即采纳，生成流程零感知（评审是增益不是依赖）。"""

    def _none(*_a: object, **_k: object) -> None:
        return None

    llm = _AlwaysOkLlm(_flow_json())
    script = _write_with_settings(tmp_path, monkeypatch, llm, _none)
    assert script.segments
    assert len(llm.prompts) == 1


def test_judge_reject_capped_then_adopt_with_annotation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """拒稿封顶 1 次：第二轮即便评分仍低也采纳（评审低分不挡片），批注进 trace。"""
    calls = {"n": 0}

    def _always_low(*_a: object, **_k: object) -> dict[str, Any]:
        calls["n"] += 1
        return {"total": 3.0, "suggestion": "还是不够狠"}

    llm = _AlwaysOkLlm(_flow_json())
    script = _write_with_settings(tmp_path, monkeypatch, llm, _always_low)
    assert script.segments
    assert calls["n"] == 2  # 轮0 拒稿一次、轮1 采纳——不是 3 轮打满
    trace = json.loads((tmp_path / "trace.json").read_text(encoding="utf-8"))
    assert trace["attempts"][-1]["judge"]["total"] == pytest.approx(3.0)


def test_default_settings_skips_judge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """settings 缺省（测试/直调路径）完全不触发评审——W6 行为逐字节不变。"""

    def _forbid(*_a: object, **_k: object) -> Any:
        raise AssertionError("未传 settings 不该跑评审")

    monkeypatch.setattr(flow_writer.variant_scoring, "score_one", _forbid)
    llm = _AlwaysOkLlm(_flow_json())
    script = flow_writer.write_flow_script(
        llm,
        _episode_inputs(),
        project_name="测试剧",
        angle_block="",
        trace_path=tmp_path / "trace.json",
    )
    assert script.segments
