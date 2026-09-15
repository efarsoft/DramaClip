"""export.submit：把已规划好的方案排队渲染。

钉四件事：① 一条方案一个 export job；② 拒绝路径逐条给理由；
③ 可渲染性守卫——没配音的方案会被静默渲成哑片（§3.3.1 禁止级）；
④ 守卫不得假设"一条片属于一集"：跨集方案每一集的旁白段都要查到。
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import export as export_api
from dramaclip.engines.narration.models import NarrationText, PlanData, TimelineSegment
from dramaclip.infra import jobs as jobs_mod
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import Router, RpcRequest
from tests.conftest import register_job_executor


def _harness(memory_db: sqlite3.Connection, tmp_path: Path) -> SimpleNamespace:
    context = SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "cache" / "analysis",
        settings={},
        notifier=Notifier(lambda _m: None),
        executor=register_job_executor(ThreadPoolExecutor(max_workers=2)),
        job_store=jobs_mod.JobStore(memory_db),
        cancel_events={},
    )
    router = Router()
    export_api.register(router, context)  # type: ignore[arg-type]
    return SimpleNamespace(context=context, router=router)


def _rpc(harness: SimpleNamespace, method: str, params: dict[str, Any]) -> Any:
    response = harness.router.dispatch(RpcRequest(id=method, method=method, params=params))
    if response.error is not None:
        raise AssertionError(f"{method} RPC 错误: [{response.error.code}] {response.error.message}")
    return response.result


def _dispatch(harness: SimpleNamespace, method: str, params: dict[str, Any]) -> Any:
    return harness.router.dispatch(RpcRequest(id=method, method=method, params=params))


def _voiced_plan(tmp_path: Path, mode: str = "full_narration") -> PlanData:
    """一条已配音的方案：音频文件真的落在盘上（守卫要 stat 它）。"""
    audio = tmp_path / "tts" / "full-1.mp3"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"mp3")
    return PlanData(
        mode=mode,
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=0.0, end=1.25, audio="ducked", narration_id="full-1",
                subtitle_text="第一段解说",
            )
        ],
        narration_texts=[
            NarrationText(id="full-1", text="第一段解说", audio_path=str(audio), duration=1.25)
        ],
    )


def _seed_plan(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    plan_data: PlanData,
    *,
    status: str = "ready",
) -> tuple[str, str]:
    project_id = str(projects_repo.create(memory_db, "提交剧", str(tmp_path))["id"])
    plan_id = str(
        plans_repo.create(
            memory_db, project_id, plan_data.mode,
            sorted({segment.episode_id for segment in plan_data.timeline}),
            plan_data.model_dump(),
            status=status,
        )["id"]
    )
    return project_id, plan_id


def test_submit_creates_one_export_job_per_plan(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    project_id, plan_id = _seed_plan(memory_db, tmp_path, _voiced_plan(tmp_path))
    harness = _harness(memory_db, tmp_path)

    result = _rpc(harness, "export.submit", {"plan_ids": [plan_id]})
    assert len(result["exports"]) == 1 and result["rejected"] == []
    entry = result["exports"][0]
    assert entry["plan_id"] == plan_id
    assert entry["export_id"] and entry["job_id"]

    jobs_row = harness.context.job_store.get(str(entry["job_id"]))
    assert jobs_row is not None and jobs_row["type"] == "export"
    assert len(exports_repo.list_by_project(memory_db, project_id)) == 1


def test_submit_dedupes_plan_ids_within_one_call(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同一次调用里重复出现的 plan_id 只出一次片。"""
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    _project_id, plan_id = _seed_plan(memory_db, tmp_path, _voiced_plan(tmp_path))
    harness = _harness(memory_db, tmp_path)

    result = _rpc(harness, "export.submit", {"plan_ids": [plan_id, plan_id, plan_id]})
    assert len(result["exports"]) == 1, f"重复 plan_id 出了多部片：{result}"


def test_submit_rejects_each_bad_plan_with_its_own_reason(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """混合批次：坏的逐条给理由，好的一起走，不许一整批炸掉。"""
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    _project_id, good = _seed_plan(memory_db, tmp_path, _voiced_plan(tmp_path))
    harness = _harness(memory_db, tmp_path)

    result = _rpc(harness, "export.submit", {"plan_ids": [good, "不存在的方案"]})
    assert [item["plan_id"] for item in result["exports"]] == [good]
    assert len(result["rejected"]) == 1
    assert result["rejected"][0]["plan_id"] == "不存在的方案"
    assert "不存在" in result["rejected"][0]["reason"]


def test_submit_rejects_an_unvoiced_narration_plan(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """守卫本体：有旁白段却没有 audio_path 的方案，渲染出来是一部哑片。"""
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    unvoiced = PlanData(
        mode="full_narration",
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=0.0, end=2.0, audio="ducked", narration_id="full-1"
            )
        ],
        narration_texts=[NarrationText(id="full-1", text="第一段解说")],
    )
    _project_id, plan_id = _seed_plan(memory_db, tmp_path, unvoiced)
    harness = _harness(memory_db, tmp_path)

    result = _rpc(harness, "export.submit", {"plan_ids": [plan_id]})
    assert result["exports"] == []
    assert "没有配音音频" in result["rejected"][0]["reason"]


def test_submit_rejects_a_plan_whose_audio_file_is_gone(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """配音文件是承重存储，丢了就地拒绝。"""
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    plan_data = _voiced_plan(tmp_path)
    _project_id, plan_id = _seed_plan(memory_db, tmp_path, plan_data)
    Path(str(plan_data.narration_texts[0].audio_path)).unlink()
    harness = _harness(memory_db, tmp_path)

    result = _rpc(harness, "export.submit", {"plan_ids": [plan_id]})
    assert result["exports"] == []
    assert "配音音频已丢失" in result["rejected"][0]["reason"]


def test_submit_rejects_a_plan_that_is_not_ready(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    _project_id, plan_id = _seed_plan(
        memory_db, tmp_path, _voiced_plan(tmp_path), status="generating"
    )
    harness = _harness(memory_db, tmp_path)

    result = _rpc(harness, "export.submit", {"plan_ids": [plan_id]})
    assert result["exports"] == []
    assert "generating" in result["rejected"][0]["reason"]


def test_submit_rejects_an_empty_timeline(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    _project_id, plan_id = _seed_plan(memory_db, tmp_path, PlanData(mode="raw_clip"))
    harness = _harness(memory_db, tmp_path)

    result = _rpc(harness, "export.submit", {"plan_ids": [plan_id]})
    assert result["exports"] == []
    assert "时间轴为空" in result["rejected"][0]["reason"]


def test_silent_modes_need_no_audio(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """raw_clip / subtitle_flow 没有旁白槽位，守卫对它们是空转。"""
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    silent = PlanData(
        mode="raw_clip",
        timeline=[TimelineSegment(episode_id="ep1", start=0.0, end=5.0, audio="original")],
    )
    _project_id, plan_id = _seed_plan(memory_db, tmp_path, silent)
    harness = _harness(memory_db, tmp_path)

    result = _rpc(harness, "export.submit", {"plan_ids": [plan_id]})
    assert result["rejected"] == [], f"无解说模式被守卫误拦：{result}"
    assert len(result["exports"]) == 1


def _cross_episode_plan(tmp_path: Path, *, unvoiced: str = "") -> PlanData:
    """横跨两集的方案，两集各一个 ducked 槽位；unvoiced 点名的那集不给音频。

    两集的区间刻意完全重合（都是 0.0-1.25s）：守卫若按 (start, end) 认段
    而不按 (episode_id, start, end)，这两段就会被当成同一段素材。
    """
    timeline: list[TimelineSegment] = []
    texts: list[NarrationText] = []
    for index, episode_id in enumerate(("ep1", "ep2"), start=1):
        slot_id = f"full-{index}"
        audio_path: str | None = None
        if episode_id != unvoiced:
            audio = tmp_path / "tts" / f"{slot_id}-{episode_id}.mp3"
            audio.parent.mkdir(parents=True, exist_ok=True)
            audio.write_bytes(b"mp3")
            audio_path = str(audio)
        timeline.append(
            TimelineSegment(
                episode_id=episode_id, start=0.0, end=1.25, audio="ducked",
                narration_id=slot_id, subtitle_text=f"第{index}段解说",
            )
        )
        texts.append(
            NarrationText(id=slot_id, text=f"第{index}段解说", audio_path=audio_path, duration=1.25)
        )
    return PlanData(mode="full_narration", timeline=timeline, narration_texts=texts)


def test_submit_accepts_a_plan_spanning_two_episodes(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """守卫不得假设"一条片属于一集"。"""
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    plan_data = _cross_episode_plan(tmp_path)
    assert len({segment.episode_id for segment in plan_data.timeline}) == 2, "夹具前提塌了"
    _project_id, plan_id = _seed_plan(memory_db, tmp_path, plan_data)
    harness = _harness(memory_db, tmp_path)

    result = _rpc(harness, "export.submit", {"plan_ids": [plan_id]})
    assert result["rejected"] == [], f"跨集方案被守卫误拦：{result['rejected']}"
    assert len(result["exports"]) == 1


def test_submit_rejects_an_unvoiced_slot_in_the_second_episode(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """守卫必须逐段查配音，包括第二集那段——跨集才存在的哑片形态。"""
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    plan_data = _cross_episode_plan(tmp_path, unvoiced="ep2")
    _project_id, plan_id = _seed_plan(memory_db, tmp_path, plan_data)
    harness = _harness(memory_db, tmp_path)

    result = _rpc(harness, "export.submit", {"plan_ids": [plan_id]})
    assert result["exports"] == [], f"第二集的哑段被放行了：{result['exports']}"
    reason = result["rejected"][0]["reason"]
    assert "没有配音音频" in reason and "ep2" in reason, (
        f"拒绝理由没点名到出问题的集：{reason}"
    )


@pytest.mark.parametrize("params", [{}, {"plan_ids": []}, {"plan_ids": "一个字符串"}])
def test_bad_plan_ids_are_rejected_at_the_rpc_boundary(
    memory_db: sqlite3.Connection, tmp_path: Path, params: dict[str, Any]
) -> None:
    harness = _harness(memory_db, tmp_path)
    response = _dispatch(harness, "export.submit", params)
    assert response.error is not None and response.error.code == -32406, response


def test_retry_shares_the_renderability_guard(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """守卫必须被 submit 与 retry 共用：只装一侧的话，重试会把哑片渲出来。"""
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    unvoiced = PlanData(
        mode="full_narration",
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=0.0, end=2.0, audio="ducked", narration_id="full-1"
            )
        ],
        narration_texts=[NarrationText(id="full-1", text="第一段解说")],
    )
    project_id, plan_id = _seed_plan(memory_db, tmp_path, unvoiced)
    export_id = exports_repo.create(memory_db, project_id, plan_id, "full_narration")
    exports_repo.mark_failed(memory_db, export_id, "上一轮渲染失败")
    harness = _harness(memory_db, tmp_path)

    response = _dispatch(harness, "export.retry", {"export_id": export_id})
    assert response.error is not None and response.error.code == -32407, response
    assert exports_repo.get(memory_db, export_id)["status"] == exports_repo.STATUS_FAILED, (
        "拒绝必须发生在 CAS 复位之前"
    )
