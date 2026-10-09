"""analysis.export_transcripts：全部已分析集一次导出逐集 SRT + 合并 TXT。

SRT 用融合转写结果（台词保护区同源数据），放回视频旁即被「同名 .srt 优先」
机制当金标准；未分析的集跳过不挡其他集；未知项目报错。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from tests.api.test_analysis import FakeTranscriber, Harness


def _seed_done_episode(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    *,
    number: int,
    name: str,
    lines: list[tuple[float, float, str]],
) -> str:
    created = projects_repo.create(memory_db, f"剧{number}", str(tmp_path / f"src{number}"))
    project_id = str(created["id"])
    source = tmp_path / f"ep{number}.mp4"
    source.write_bytes(b"x")
    episodes_repo.replace_all(
        memory_db,
        project_id,
        [{"episode_number": number, "name": name, "source_path": str(source), "duration": 120.0}],
    )
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    segs = [{"start": start, "end": end, "text": text} for start, end, text in lines]
    analysis_repo.upsert(
        memory_db,
        episode_id,
        asr_segments=json.dumps(segs, ensure_ascii=False),
        scene_data="[]",
        audio_features="{}",
    )
    episodes_repo.set_status(memory_db, episode_id, "done")
    return project_id


def test_export_writes_srt_and_combined_txt(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    project_id = _seed_done_episode(
        memory_db,
        tmp_path,
        number=1,
        name="大明：灭国前，我觉醒了-第1集",
        lines=[(0.2, 1.4, "陛下，五十一万两银子不见了"), (1.6, 3.0, "把户部尚书给我拿下")],
    )
    harness = Harness(
        memory_db, tmp_path / "cache" / "analysis", FakeTranscriber(), data_dir=tmp_path
    )
    result = harness.rpc("analysis.export_transcripts", {"project_id": project_id})
    assert result["ok"] is True and result["exported"] == 1 and result["skipped"] == 0
    out = Path(result["dir"])
    srt_files = list(out.glob("*.srt"))
    assert len(srt_files) == 1, "每集一个 SRT"
    text = srt_files[0].read_text(encoding="utf-8")
    assert "-->" in text, "SRT 时间轴"
    assert "陛下，五十一万两银子不见了" in text, "SRT 含台词"
    txt = Path(result["txt_path"])
    txt_content = txt.read_text(encoding="utf-8")
    assert "全剧台词" in txt_content and "把户部尚书给我拿下" in txt_content


def test_unanalyzed_episode_is_skipped(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    project_id = str(projects_repo.create(memory_db, "剧", str(tmp_path / "src"))["id"])
    episodes_repo.replace_all(
        memory_db,
        project_id,
        [
            {"episode_number": 1, "name": "第1集", "source_path": "a.mp4", "duration": 60.0},
            {"episode_number": 2, "name": "第2集", "source_path": "b.mp4", "duration": 60.0},
        ],
    )
    episode_one = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    analysis_repo.upsert(
        memory_db,
        episode_one,
        asr_segments=json.dumps([{"start": 0.0, "end": 2.0, "text": "仅有的一句"}]),
        scene_data="[]",
        audio_features="{}",
    )
    episodes_repo.set_status(memory_db, episode_one, "done")
    harness = Harness(
        memory_db, tmp_path / "cache" / "analysis", FakeTranscriber(), data_dir=tmp_path
    )
    result = harness.rpc("analysis.export_transcripts", {"project_id": project_id})
    assert result["exported"] == 1 and result["skipped"] == 1


def test_unknown_project_raises(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    harness = Harness(
        memory_db, tmp_path / "cache" / "analysis", FakeTranscriber(), data_dir=tmp_path
    )
    with pytest.raises(Exception, match="项目不存在"):
        harness.rpc("analysis.export_transcripts", {"project_id": "nope"})
