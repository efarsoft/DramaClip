"""script_driver：跨集剧本编排装配——选题降级链与降级路径。"""

from __future__ import annotations

from typing import Any

import pytest

from dramaclip.engines.narration import script_driver


def _noop_log(_level: str, _message: str) -> None:
    """静默日志桩。"""


_SETTINGS: dict[str, str] = {
    "llm.base_url": "http://llm.test/v1",
    "llm.api_key": "sk-test",
    "llm.model": "test-model",
    "narration.style_id": "auto",
    "_project_name": "测试剧",
    "_genre": "逆袭",
    "strategy.min_duration_s": "30",
    "strategy.max_duration_s": "300",
}

_EPISODES: list[dict[str, Any]] = [
    {
        "number": 1,
        "episode_id": "ep-1",
        "duration": 100.0,
        "segments": [{"start": 1.0, "end": 10.0, "text": "第一集台词"}],
    },
    {
        "number": 2,
        "episode_id": "ep-2",
        "duration": 90.0,
        "segments": [{"start": 5.0, "end": 15.0, "text": "第二集台词"}],
    },
]

_SCRIPT_PAYLOAD: dict[str, Any] = {
    "hook": "钩子",
    "segments": [
        {"episode": 1, "start": 1.0, "end": 10.0, "text": "第一集解说"},
        {"episode": 2, "start": 5.0, "end": 15.0, "text": "第二集解说"},
    ],
    "cta": "点我看结局",
}


class FakeLlmClient:
    """按队列响应 chat_json；记录调用供断言。"""

    calls: list[str] = []
    queue: list[Any] = []

    def __init__(self, _config: Any, timeout_s: float = 60.0) -> None:
        self.timeout_s = timeout_s

    def chat_json(self, _system: str, _user: str) -> Any:
        FakeLlmClient.calls.append(_user)
        queue = FakeLlmClient.queue
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture()
def driver(monkeypatch: pytest.MonkeyPatch) -> Any:
    FakeLlmClient.queue = []
    FakeLlmClient.calls = []
    monkeypatch.setattr(script_driver, "LlmClient", FakeLlmClient)
    return script_driver


def test_llm_unconfigured_returns_none() -> None:
    settings = dict(_SETTINGS)
    settings["llm.base_url"] = ""
    assert script_driver.script_dialogue_plan(_EPISODES, settings, log=_noop_log) is None


def test_manual_style_skips_selection_call(driver: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = dict(_SETTINGS)
    settings["narration.style_id"] = "shuanggan"
    FakeLlmClient.queue = [dict(_SCRIPT_PAYLOAD)]
    plan, used = script_driver.script_dialogue_plan(_EPISODES, settings, log=_noop_log)
    assert plan is not None and plan.planner == "llm_script"
    assert len(FakeLlmClient.calls) == 1, "手动风格应跳过选题调用"
    assert used == ["ep-1", "ep-2"]


def test_auto_selects_style_then_writes(driver: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    FakeLlmClient.queue = [
        {"style_id": "shuanggan", "reason": "打脸弧线完整"},
        dict(_SCRIPT_PAYLOAD),
    ]
    plan, used = script_driver.script_dialogue_plan(_EPISODES, dict(_SETTINGS), log=_noop_log)
    assert plan is not None and plan.planner == "llm_script"
    assert used == ["ep-1", "ep-2"]


def test_selection_failure_falls_back_to_genre(
    driver: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    FakeLlmClient.queue = [
        RuntimeError("选题服务不可用"),
        dict(_SCRIPT_PAYLOAD),
    ]
    logs: list[tuple[str, str]] = []

    def log(level: str, message: str) -> None:
        logs.append((level, message))

    plan, used = script_driver.script_dialogue_plan(_EPISODES, dict(_SETTINGS), log=log)
    assert plan is not None and plan.planner == "llm_script"
    assert any("题材静态映射" in message for _level, message in logs)
