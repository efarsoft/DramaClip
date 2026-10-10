"""mode_recommend：AI 模式推荐的缓存、校验与兜底。

三块判据：①缓存语义——命中不调 LLM，refresh 才重算并覆盖；②合法性——
菜单外的模式剔除、不足三个按通用序补位且补位如实标注；③兜底——LLM 未配置/
不可用/返回不合法都回静态三件套（模型稳定性由用户选型保障，推荐不掺保底位）。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from dramaclip.api import narration as narration_api
from dramaclip.engines.narration import mode_recommend
from dramaclip.engines.semantic.llm_client import LlmUnavailable
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.rpc import RpcDomainError


class _FakeLlm:
    instances: list[_FakeLlm] = []
    reply: dict = {}

    def __init__(self, _config: object, timeout_s: float = 60.0) -> None:
        self.timeout_s = timeout_s
        _FakeLlm.instances.append(self)

    def chat_json(self, _system: str, user: str, temperature: float = 0.3) -> dict:
        self.last_user = user
        if isinstance(_FakeLlm.reply, Exception):
            raise _FakeLlm.reply
        return _FakeLlm.reply


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> type[_FakeLlm]:
    _FakeLlm.instances = []
    _FakeLlm.reply = {"modes": []}

    class _FakeConfig:
        configured = True

        @staticmethod
        def from_settings(_settings: dict) -> _FakeConfig:
            return _FakeConfig()

    monkeypatch.setattr(mode_recommend, "LlmConfig", _FakeConfig)
    monkeypatch.setattr(mode_recommend, "LlmClient", _FakeLlm)
    return _FakeLlm


def _project_with_analysis(memory_db: sqlite3.Connection, tmp_path: Path) -> str:
    project = projects_repo.create(memory_db, "剧", str(tmp_path))
    project_id = str(project["id"])
    episodes_repo.replace_all(
        memory_db,
        project_id,
        [
            {"episode_number": 1, "source_path": str(tmp_path / "ep1.mp4"), "duration": 60.0},
            {"episode_number": 2, "source_path": str(tmp_path / "ep2.mp4"), "duration": 60.0},
        ],
    )
    for episode in episodes_repo.list_by_project(memory_db, project_id):
        analysis_repo.upsert(
            memory_db,
            str(episode["id"]),
            asr_segments='[{"start":0,"end":1,"text":"台词","words":[]}]',
            scene_data="[]",
            audio_features="{}",
            highlights=json.dumps(
                [
                    {"start": 0, "end": 5, "score": 9.0, "reason": "顶罪受辱"},
                    {"start": 30, "end": 40, "score": 8.0, "reason": "龙王觉醒反杀"},
                ]
            ),
            genre="逆袭",
        )
    return project_id


def test_llm_recommendation_cached_until_refresh(
    memory_db: sqlite3.Connection, tmp_path: Path, fake_llm: type[_FakeLlm]
) -> None:
    project_id = _project_with_analysis(memory_db, tmp_path)
    fake_llm.reply = {
        "modes": [
            {"mode": "dialogue_narration", "reason": "反转弧完整"},
            {"mode": "cross_narration", "reason": "打脸节点密"},
            {"mode": "full_narration", "reason": "冲突密度最高"},
        ]
    }

    first = mode_recommend.recommend(memory_db, project_id, {}, refresh=False)
    assert [m["mode"] for m in first["modes"]] == [
        "dialogue_narration",
        "cross_narration",
        "full_narration",
    ]
    assert first["genre"] == "逆袭"

    cached = projects_repo.get_settings(memory_db, project_id)["mode_recommendation"]
    assert cached == first, "推荐必须随项目落缓存"

    second = mode_recommend.recommend(memory_db, project_id, {}, refresh=False)
    assert second == first
    assert len(fake_llm.instances) == 1, "缓存命中不再调 LLM"

    mode_recommend.recommend(memory_db, project_id, {}, refresh=True)
    assert len(fake_llm.instances) == 2, "refresh 显式重算"


def test_prompt_carries_genre_and_highlight_reasons(
    memory_db: sqlite3.Connection, tmp_path: Path, fake_llm: type[_FakeLlm]
) -> None:
    project_id = _project_with_analysis(memory_db, tmp_path)
    fake_llm.reply = {"modes": []}
    mode_recommend.recommend(memory_db, project_id, {}, refresh=False)
    user = fake_llm.instances[0].last_user
    assert "逆袭" in user and "顶罪受辱" in user, "推荐依据必须真喂给 LLM"


def test_invalid_modes_filtered_and_padded(
    memory_db: sqlite3.Connection, tmp_path: Path, fake_llm: type[_FakeLlm]
) -> None:
    project_id = _project_with_analysis(memory_db, tmp_path)
    fake_llm.reply = {
        "modes": [
            {"mode": "nope", "reason": "菜单外"},
            {"mode": "dialogue_narration", "reason": "合法"},
            {"mode": "dialogue_narration", "reason": "重复"},
        ]
    }

    result = mode_recommend.recommend(memory_db, project_id, {}, refresh=False)

    modes = [m["mode"] for m in result["modes"]]
    assert len(modes) == 3
    assert modes[0] == "dialogue_narration"
    assert "补位" in result["modes"][1]["reason"], "补位项如实标注，不冒充 AI 判断"


def test_llm_unavailable_falls_back(
    memory_db: sqlite3.Connection, tmp_path: Path, fake_llm: type[_FakeLlm]
) -> None:
    project_id = _project_with_analysis(memory_db, tmp_path)
    fake_llm.reply = LlmUnavailable("读超时")

    result = mode_recommend.recommend(memory_db, project_id, {}, refresh=False)

    assert [m["mode"] for m in result["modes"]] == mode_recommend._FALLBACK_ORDER
    assert "LLM 不可用" in result["modes"][0]["reason"]


def test_unconfigured_llm_never_constructed(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id = _project_with_analysis(memory_db, tmp_path)
    result = mode_recommend.recommend(memory_db, project_id, {}, refresh=False)
    assert [m["mode"] for m in result["modes"]] == mode_recommend._FALLBACK_ORDER


def test_rpc_rejects_missing_project(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    context = SimpleNamespace(conn=memory_db, settings={}, data_dir=tmp_path, work_dir=tmp_path)
    with pytest.raises(RpcDomainError, match="项目不存在"):
        narration_api.recommend_modes(context, {"project_id": "nope"})
