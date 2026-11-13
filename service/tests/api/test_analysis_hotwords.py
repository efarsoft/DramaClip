"""人工热词的剧级隔离（2026-11-12 业主裁决：全局键改项目级）。

一部剧点名的专名只喂这一部剧；全局残留（老库里删不净的手改行）不再被消费。
走 OCR 关闭分支直取热词合并结果，不起作业线程。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from dramaclip.api import analysis_job
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import projects as projects_repo


def _project(
    memory_db: sqlite3.Connection, tmp_path: Path, name: str
) -> tuple[str, list[dict[str, Any]]]:
    project = projects_repo.create(memory_db, name, str(tmp_path / name))
    project_id = str(project["id"])
    episodes_repo.replace_all(
        memory_db,
        project_id,
        [
            {
                "episode_number": 1,
                "source_path": str(tmp_path / f"{name}-1.mp4"),
                "duration": 60.0,
            }
        ],
    )
    return project_id, episodes_repo.list_by_project(memory_db, project_id)


def _context(memory_db: sqlite3.Connection, tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "work",
        # 全局键残留：即使有人往库里手写回全局行，也不得再被消费（跨剧泄漏源）
        settings={"analysis.ocr_enabled": "0", "asr.hotwords_extra": "全局残留"},
    )


def test_hotwords_come_from_the_project_not_the_global_settings(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    drama_a, episodes_a = _project(memory_db, tmp_path, "历史剧")
    drama_b, episodes_b = _project(memory_db, tmp_path, "现代剧")
    projects_repo.update_settings(memory_db, drama_a, {"asr.hotwords_extra": "骆养性、崇祯"})

    context = _context(memory_db, tmp_path)
    hotwords_a = analysis_job._mine_hotwords(  # noqa: SLF001 - 直取阶段 A 的合并结果
        context, episodes_a, threading.Event(), project_id=drama_a
    )[3]
    hotwords_b = analysis_job._mine_hotwords(  # noqa: SLF001
        context, episodes_b, threading.Event(), project_id=drama_b
    )[3]

    assert "骆养性" in hotwords_a and "崇祯" in hotwords_a, "点名的专名要进本剧热词表"
    assert "全局残留" not in hotwords_a, "全局键不得再被消费"
    assert hotwords_b == "", "没点名热词的剧不吃别剧的热词"


def test_hotwords_accept_all_declared_separators(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """顿号/全角逗号/半角逗号/空格四种分隔皆收（与全局键时代同一合并器）。"""
    drama, episodes = _project(memory_db, tmp_path, "分隔剧")
    projects_repo.update_settings(
        memory_db, drama, {"asr.hotwords_extra": "甲、乙，丙, 丁"}
    )
    hotwords = analysis_job._mine_hotwords(  # noqa: SLF001
        _context(memory_db, tmp_path), episodes, threading.Event(), project_id=drama
    )[3]
    assert hotwords.split() == ["甲", "乙", "丙", "丁"]
