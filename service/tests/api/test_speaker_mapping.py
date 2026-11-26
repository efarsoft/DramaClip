"""真名映射（v0.2.5 2.2）：RPC 读写（project.settings 单键）+ 原料装配应用。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from dramaclip.api import analysis as analysis_api
from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.flows import narration as flows_narration
from dramaclip.infra import jobs as jobs_mod
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import RpcDomainError


def _context(memory_db: sqlite3.Connection, tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "work",
        settings={},
        analysis_runtime=SimpleNamespace(transcriber=lambda: SimpleNamespace(name="fake")),
        job_store=jobs_mod.JobStore(memory_db),
        cancel_events={},
        executor=None,
        notifier=Notifier(lambda _m: None),
    )


def _project_with_episode(memory_db: sqlite3.Connection, tmp_path: Path) -> str:
    project = projects_repo.create(memory_db, "剧", str(tmp_path))
    episodes_repo.replace_all(
        memory_db,
        str(project["id"]),
        [
            {
                "episode_number": 1,
                "source_path": str(tmp_path / "ep1.mp4"),
                "duration": 60.0,
            }
        ],
    )
    return str(project["id"])


def test_speaker_mapping_write_read_round_trip(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """写→落 project.settings 单键（JSON 串）；键值去空白；读回同形。"""
    project_id = _project_with_episode(memory_db, tmp_path)
    context = _context(memory_db, tmp_path)
    res = analysis_api.speaker_mapping(
        context,
        {"project_id": project_id, "mapping": {"角色A": "汪言", " 角色B ": " 娇娇 "}},
    )
    assert res["mapping"] == {"角色A": "汪言", "角色B": "娇娇"}
    raw = projects_repo.get_settings(memory_db, project_id)["speaker.mapping"]
    assert isinstance(raw, str) and "汪言" in raw, "settings 单键存 JSON 串"
    again = analysis_api.speaker_mapping(context, {"project_id": project_id})
    assert again["mapping"] == {"角色A": "汪言", "角色B": "娇娇"}


def test_speaker_mapping_validation(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    """非对象/超量 → -32207；空键或空值条目被丢弃（清空=删映射）。"""
    project_id = _project_with_episode(memory_db, tmp_path)
    context = _context(memory_db, tmp_path)
    with pytest.raises(RpcDomainError) as excinfo:
        analysis_api.speaker_mapping(context, {"project_id": project_id, "mapping": ["坏"]})
    assert excinfo.value.code == -32207
    with pytest.raises(RpcDomainError) as excinfo:
        analysis_api.speaker_mapping(
            context,
            {"project_id": project_id, "mapping": {f"角色{k}": f"名{k}" for k in range(61)}},
        )
    assert excinfo.value.code == -32207
    res = analysis_api.speaker_mapping(
        context, {"project_id": project_id, "mapping": {"角色A": "   ", "角色B": "娇娇"}}
    )
    assert res["mapping"] == {"角色B": "娇娇"}, "空白真名=删除该映射条目"


def test_speaker_mapping_unknown_project(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    context = _context(memory_db, tmp_path)
    with pytest.raises(RpcDomainError) as excinfo:
        analysis_api.speaker_mapping(context, {"project_id": "ghost"})
    assert excinfo.value.code == -32101


def test_apply_speaker_mapping_maps_and_passes_through() -> None:
    """映射命中替换、未映射与无标签原样；空映射原列表直通（零改动语义）。"""
    segs = [
        AsrSegment(start=0.0, end=1.0, text="甲", speaker="角色A"),
        AsrSegment(start=1.0, end=2.0, text="乙"),
    ]
    out = flows_narration._apply_speaker_mapping(segs, {"角色A": "汪言"})
    assert out[0].speaker == "汪言"
    assert out[1].speaker is None
    assert flows_narration._apply_speaker_mapping(segs, {}) is segs, "空映射直通原列表"


def test_speaker_mapping_of_parses_settings_json() -> None:
    assert flows_narration._speaker_mapping_of(
        {"speaker.mapping": '{"角色A": "汪言"}'}
    ) == {"角色A": "汪言"}
    assert flows_narration._speaker_mapping_of({}) == {}
    assert flows_narration._speaker_mapping_of({"speaker.mapping": "not-json"}) == {}
    assert flows_narration._speaker_mapping_of({"speaker.mapping": "42"}) == {}


def test_collect_episode_inputs_applies_mapping(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """原料装配（编剧/选题链入口）吃映射：seg.speaker 落真名。"""
    project_id = _project_with_episode(memory_db, tmp_path)
    context = _context(memory_db, tmp_path)
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    analysis_repo.upsert(
        memory_db,
        episode_id,
        asr_segments=json.dumps(
            [{"start": 1.0, "end": 3.0, "text": "台词", "speaker": "角色A"}]
        ),
        scene_data=None,
        audio_features=None,
    )
    episodes = episodes_repo.list_by_project(memory_db, project_id)
    inputs = flows_narration._collect_episode_inputs(
        context, episodes, {"角色A": "汪言"}
    )
    assert inputs[0]["segments"][0]["speaker"] == "汪言"
    unmapped = flows_narration._collect_episode_inputs(context, episodes, None)
    assert unmapped[0]["segments"][0]["speaker"] == "角色A"
