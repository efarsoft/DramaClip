"""script_driver：任务级口味层解析（`resolve_run_style`）+ 跨集剧本装配。"""

from __future__ import annotations

import json
from typing import Any

import pytest

from dramaclip.engines.narration import script_driver
from dramaclip.engines.semantic.llm_client import LlmUnavailable
from tests.llm_stub import patch_client_for


def _noop_log(_level: str, _message: str) -> None:
    """静默日志桩。"""


_SETTINGS: dict[str, str] = {
    "llm.base_url": "http://llm.test/v1",
    "llm.api_key": "sk-test",
    "llm.model": "test-model",
    "narration.style_id": "auto",
    "_project_name": "测试剧",
    "_genre": "逆袭",
}

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
        "episode_id": "ep-1",
        "duration": 100.0,
        "segments": [
            {"start": 1.0, "end": 10.0, "text": "第一集台词"},
            {"start": 10.0, "end": 20.0, "text": "第一集台词续"},
        ],
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
    """按队列响应 chat_json；记录 system/user 供断言哪一层被调用。"""

    calls: list[tuple[str, str]] = []
    queue: list[Any] = []

    def __init__(self, _config: Any, timeout_s: float = 60.0) -> None:
        self.timeout_s = timeout_s

    def chat_json(self, system: str, user: str, temperature: float = 0.3) -> Any:
        FakeLlmClient.calls.append((system, user))
        queue = FakeLlmClient.queue
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture()
def driver(monkeypatch: pytest.MonkeyPatch) -> Any:
    FakeLlmClient.queue = []
    FakeLlmClient.calls = []
    FakeLlmClient.systems = []
    patch_client_for(monkeypatch, script_driver, FakeLlmClient)
    return script_driver


def test_unconfigured_llm_raises_not_none() -> None:
    """降级禁止：LLM 未配置时报错并说明去配什么，绝不悄悄出一版规则编排。"""
    settings = dict(_SETTINGS)
    settings["llm.base_url"] = ""
    with pytest.raises(LlmUnavailable, match="引擎"):
        script_driver.script_dialogue_plan(_EPISODES, settings, angle_block="",
        min_segments=2,
        )



def test_no_script_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_client_for(monkeypatch, script_driver, FakeLlmClient)
    FakeLlmClient.queue = [{"hook": "", "segments": []}]
    with pytest.raises(ValueError, match="剧本"):
        script_driver.script_dialogue_plan(_EPISODES, dict(_SETTINGS), angle_block="",
        min_segments=2,
        )



def test_resolve_run_style_auto_never_calls_llm(driver: Any) -> None:
    """auto 不再跑 LLM 风格选题（2026-10-20 裁决）：情绪配方随母题卡自动落定
    （angles.prompt_block 注入），口味层零 LLM 往返；题材静态映射只作通用底。"""
    FakeLlmClient.queue = [{"style_id": "sweet", "reason": "甜宠互动密集"}]
    style = driver.resolve_run_style(dict(_SETTINGS), _EPISODES, log=_noop_log)
    assert FakeLlmClient.calls == [], "auto 风格选题已退役，一个请求都不该发"
    assert style["style_id"] == "shuanggan", "_genre=逆袭 的静态映射底仍在"


def test_resolve_run_style_manual_skips_llm(driver: Any) -> None:
    FakeLlmClient.queue = [{"style_id": "sweet", "reason": "x"}]
    settings = dict(_SETTINGS)
    settings["narration.style_id"] = "suspense"
    style = driver.resolve_run_style(settings, _EPISODES, log=lambda *_a: None)
    assert style["style_id"] == "suspense"
    assert FakeLlmClient.calls == [], "手动指定风格不该发选题请求"


def test_resolve_run_style_genre_mapping_is_the_floor(driver: Any) -> None:
    """未选风格时的通用底：题材静态映射（LLM 选题路径已退役，无降级可言）。"""
    style = driver.resolve_run_style(dict(_SETTINGS), _EPISODES, log=_noop_log)
    assert style["style_id"] == "shuanggan", "_SETTINGS 的 _genre=逆袭 应映射爽感"


def test_resolve_run_style_unconfigured_skips_llm(driver: Any) -> None:
    """未配置 LLM：一个请求都不发，但题材映射照样给出可用风格（失败留给文案层报）。"""
    settings = dict(_SETTINGS)
    settings["llm.model"] = ""
    style = driver.resolve_run_style(settings, _EPISODES, log=_noop_log)
    assert FakeLlmClient.calls == [], "未配置也要发选题请求 = 七模式白撞七次网关"
    assert style["style_id"] == "shuanggan"


def test_script_plan_injects_directives_without_selection(driver: Any) -> None:
    """剧本装配不再选题：风格由任务级注入，本函数只把它交给编剧。"""
    planted = "每三句一个反问，把爽点砸实"
    settings = dict(_SETTINGS)
    settings["_style_directives"] = planted
    FakeLlmClient.queue = [dict(_SCRIPT_PAYLOAD)]
    plan, used = script_driver.script_dialogue_plan(_EPISODES, settings, angle_block="",
    min_segments=2,
    )

    assert plan.planner == "llm_script"
    assert used == ["ep-1", "ep-2"]
    assert len(FakeLlmClient.calls) == 1, f"剧本装配不该再发选题请求：{FakeLlmClient.calls}"
    assert not any("风格库" in system for system in FakeLlmClient.systems)
    assert planted in FakeLlmClient.calls[0][1], "注入的风格指令未进编剧 prompt"


def test_angle_block_is_forwarded_to_the_script_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """跨集链的角度注入：与单集链共用 angles.prompt_block 的措辞，不得各写一份。"""
    patch_client_for(monkeypatch, script_driver, FakeLlmClient)
    FakeLlmClient.queue = [dict(_VALID_PAYLOAD)]
    script_driver.script_dialogue_plan(
        _EPISODES, dict(_SETTINGS), angle_block="\n本条片的取材角度：复仇线",
    min_segments=2,
    )

    assert any("复仇线" in call[1] for call in FakeLlmClient.calls), (
        "角度块没转交到编剧 prompt"
    )


# --------------------------------------------------------------- 留痕与丢弃数
# 选题与清洗是两处"结果悄悄变差、界面上毫无痕迹"的环节：一次是模型答的非库内风格，
# 一次是清洗层吃掉整段剧本。两处都得留下可对账的数字。


def _blobs(tmp_path: Any) -> list[dict[str, Any]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(tmp_path.glob("*.json"))
    ]




def test_manual_style_writes_no_trace(driver: Any, tmp_path: Any) -> None:
    """手动指定风格根本不发请求，留一个空壳文件等于伪造证据。"""
    settings = dict(_SETTINGS)
    settings["narration.style_id"] = "suspense"
    driver.resolve_run_style(settings, _EPISODES, log=_noop_log, trace_dir=tmp_path)
    assert _blobs(tmp_path) == []


def test_script_plan_carries_what_the_sanitizer_ate(driver: Any) -> None:
    """清洗吃掉的段数随方案落库：界面上的「剧本丢弃 N 段」只有这一条来源。"""
    payload = {
        "hook": "钩子",
        "segments": [
            {"episode": 1, "start": 1.0, "end": 10.0, "text": "第一集解说"},
            {"episode": 2, "start": 5.0, "end": 15.0, "text": "第二集解说"},
            {"episode": 9, "start": 1.0, "end": 8.0, "text": "不存在的第九集"},
        ],
        "cta": "点我看结局",
    }
    FakeLlmClient.queue = [payload]
    plan, _used = script_driver.script_dialogue_plan(
        _EPISODES, dict(_SETTINGS), angle_block="",
    min_segments=2,
    )

    assert plan.dropped_segments == 1
