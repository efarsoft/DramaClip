"""零文案模式的标题/发布物料生成（发布套件补全）：raw_clip/金句流不再一票拒绝。"""

import pytest

from dramaclip.engines.narration import titles
from dramaclip.engines.semantic.llm_client import LlmUnavailable


class _FakeLlm:
    def __init__(self, reply: dict) -> None:
        self.reply = reply
        self.user = ""

    def chat_json(self, system: str, user: str, temperature: float | None = None) -> dict:
        self.user = user
        return self.reply


def _settings() -> dict[str, str]:
    return {
        "llm.api_key": "k",
        "llm.base_url": "https://api.test/v4",
        "llm.model": "test-model",
    }


def test_zero_copy_raw_clip_uses_project_brief(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """纯原片剪辑无 narration_texts：内容依据退到剧名/角度 brief，不再一票拒绝。"""
    plan = {
        "mode": "raw_clip",
        "narration_texts": [],
        "timeline": [
            {"episode_id": "ep1", "start": 0.0, "end": 8.0, "audio": "original"}
        ],
    }
    llm = _FakeLlm(
        {
            "titles": ["婚礼上她当众悔婚", "这场婚礼就是个局"],
            "caption": "婚都结到一半她喊停",
            "tags": ["爽剧"],
        }
    )
    monkeypatch.setattr(titles, "client_for", lambda *a, **k: llm)
    result = titles.generate(
        plan,
        _settings(),
        trace_path=None,
        project_brief="剧名：《钟情错付》\n取材角度：全场换新娘\n取材集：第 6、8 集",
    )
    assert result["titles"][0]["text"].startswith("婚礼")
    assert "剧名：《钟情错付》" in llm.user and "取材角度" in llm.user


def test_zero_copy_subtitle_flow_uses_golden_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """金句流：时间轴上的金句字幕就是内容依据，逐行进 prompt。"""
    plan = {
        "mode": "subtitle_flow",
        "narration_texts": [],
        "timeline": [
            {
                "episode_id": "ep1",
                "start": 30.0,
                "end": 34.0,
                "audio": "original",
                "subtitle_text": "我作为未婚妻，不该过来看看吗？",
            }
        ],
    }
    llm = _FakeLlm(
        {"titles": ["未婚妻当众发难"], "caption": "这场婚礼要变天", "tags": ["爽剧"]}
    )
    monkeypatch.setattr(titles, "client_for", lambda *a, **k: llm)
    result = titles.generate(plan, _settings(), trace_path=None)
    assert "不该过来看看吗" in llm.user, "金句字幕必须作为内容依据进 prompt"
    assert result["caption"] == "这场婚礼要变天"


def test_no_basis_still_refuses() -> None:
    """两头都没内容依据：维持原拒绝（不静默出空标题）。"""
    plan = {"mode": "raw_clip", "narration_texts": [], "timeline": []}
    with pytest.raises((ValueError, LlmUnavailable)):
        titles.generate(plan, _settings(), trace_path=None, project_brief=None)
