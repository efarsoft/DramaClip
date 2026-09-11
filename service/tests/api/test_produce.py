"""narration.produce：组合任务（编排→自动渲染）端到端（确定性数据直种）。"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import analysis as analysis_api
from dramaclip.api import export as export_api
from dramaclip.api import narration as narration_api
from dramaclip.api import project as project_api
from dramaclip.engines.analysis.models import AudioFeatures
from dramaclip.engines.narration import copywriter, pipeline, script_driver, styles
from dramaclip.engines.narration.models import PlanData
from dramaclip.infra import jobs
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import Router, RpcRequest


class Harness:
    def __init__(self, conn: sqlite3.Connection, work_dir: Path, *, data_dir: Path) -> None:
        self.sent: list[dict[str, Any]] = []
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.context = SimpleNamespace(
            conn=conn,
            work_dir=work_dir,
            data_dir=data_dir,
            settings={"asr.language": "zh"},
            notifier=Notifier(self.sent.append),
            executor=self.executor,
            job_store=jobs.JobStore(conn),
            cancel_events={},
        )
        self.router = Router()
        analysis_api.register(self.router, self.context)  # type: ignore[arg-type]
        project_api.register(self.router, self.context)  # type: ignore[arg-type]
        narration_api.register(self.router, self.context)  # type: ignore[arg-type]
        export_api.register(self.router, self.context)  # type: ignore[arg-type]

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        response = self.router.dispatch(
            RpcRequest(id=method, method=method, params=params or {})
        )
        if response.error is not None:
            raise AssertionError(
                f"{method} RPC 错误: [{response.error.code}] {response.error.message}"
            )
        return response.result

    def wait_job(self, job_id: str, timeout_s: float = 60.0) -> dict[str, Any]:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            status = self.rpc("analysis.status", {"job_id": job_id})
            if status["status"] in ("completed", "failed", "cancelled"):
                return status
            time.sleep(0.05)
        raise AssertionError("任务超时")


def _seed_project_with_analysis(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> str:
    """建项目 + 扫描 + 直种确定性分析数据（单集标记 done），返回 project_id。"""
    shutil.copy(sample_video, tmp_path / "ep1.mp4")
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    project = harness.rpc("project.create", {"name": "出片", "source_path": str(tmp_path)})
    harness.rpc("project.scan_episodes", {"project_id": project["id"]})
    project_id = str(project["id"])
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    scenes = [
        {"scene_index": i, "start": float(i), "end": float(i + 0.8), "score": 40 + i * 15}
        for i in range(3)
    ]
    analysis_repo.upsert(
        memory_db,
        episode_id,
        asr_segments=json.dumps(
            [
                {"start": 0.2, "end": 0.8, "text": "台词一"},
                {"start": 1.0, "end": 1.6, "text": "台词二"},
            ]
        ),
        scene_data="[]",
        audio_features=AudioFeatures().model_dump_json(),
        conflict_scores=json.dumps(scenes),
        highlights=json.dumps(
            [{"scene_index": 2, "start": 2.0, "end": 2.8, "score": 64, "reason": "冲突"}]
        ),
    )
    episodes_repo.set_status(memory_db, episode_id, "done")
    return project_id


def _done_episodes(conn: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
    """与 narration.produce / generate_plans 入口同口径：只取分析完成的集。"""
    return [
        episode
        for episode in episodes_repo.list_by_project(conn, project_id)
        if episode["status"] == "done"
    ]


def test_produce_renders_work_end_to_end(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    project_id = _seed_project_with_analysis(memory_db, tmp_path, sample_video)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    produce = harness.rpc(
        "narration.produce", {"project_id": project_id, "modes": ["raw_clip"]}
    )
    status = harness.wait_job(str(produce["job_id"]))
    assert status["status"] == "completed", status.get("error")

    exports = harness.rpc("export.list", {"project_id": project_id})
    assert exports[0]["status"] == "completed"
    assert Path(str(exports[0]["output_path"])).is_file()

    works = harness.rpc("export.list_works", {"project_id": project_id})
    assert any(item["project_id"] == project_id for item in works)


def test_produce_invalid_mode(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    project = harness.rpc("project.create", {"name": "x", "source_path": str(tmp_path)})
    response = harness.router.dispatch(
        RpcRequest(
            id=1,
            method="narration.produce",
            params={"project_id": project["id"], "modes": ["nope"]},
        )
    )
    assert response.error is not None and response.error.code == -32302


def test_style_selection_runs_once_per_job(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """produce 一次跑多个模式，口味层选题只该付一次 LLM 往返。"""
    project_id = _seed_project_with_analysis(memory_db, tmp_path, sample_video)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings["narration.style_id"] = "auto"

    calls: list[int] = []
    monkeypatch.setattr(
        script_driver,
        "resolve_run_style",
        lambda *_a, **_k: calls.append(1) or {"style_id": "shuanggan", "directives": "砸爽点"},
    )
    # 编排本体与本题无关：桩掉它，免得为一个计数等七次真实 LLM 成稿
    monkeypatch.setattr(narration_api, "_generate_one", lambda *_a, **_k: None)

    produce = harness.rpc(
        "narration.produce",
        {"project_id": project_id,
         "modes": ["intro_narration", "cross_narration", "full_narration"]},
    )
    harness.wait_job(str(produce["job_id"]))
    assert len(calls) == 1, f"选题被调 {len(calls)} 次，应为每任务一次"


def test_only_sound_only_modes_skip_tts_group() -> None:
    """分组只决定「谁可与配音并行」，两处代码完全同形，套件里再无第二处看得见这个集合。

    剧情解说在剧本链落地后每段都要配音，留在无 TTS 组等于宣称它没有旁白。
    """
    tts_free = frozenset({"raw_clip", "subtitle_flow"})
    assert tts_free == narration_api._NO_TTS_MODES


_PLANTED_STYLE_ID = "i2-style"
_PLANTED_DIRECTIVES = "只用反问句砸爽点"


class _FakeLlm:
    """口味层选题与语言层成稿共用一个网关替身：按 system 认出是哪一层。"""

    calls: list[tuple[str, str]] = []

    def __init__(self, _config: Any, timeout_s: float = 60.0) -> None:
        self.timeout_s = timeout_s

    def chat_json(self, system: str, user: str) -> Any:
        _FakeLlm.calls.append((system, user))
        if "风格库" in system:  # styles._SELECT_SYSTEM_PROMPT
            return {"style_id": _PLANTED_STYLE_ID, "reason": "全剧靠反问推进"}
        slots = re.findall(r"^\[([^\]]+)\] 要做的事：", user, flags=re.MULTILINE)
        return {"lines": [{"id": slot, "text": f"{slot} 的解说"} for slot in slots]}


class _StubTts:
    """落成 0 字节 mp3 即返回；时长探测已打桩（真引擎对空文案会失败）。"""

    def synthesize(self, text: str, _voice: str | None, out_path: Path) -> Path:
        assert text.strip(), "语言层没填上文案，槽位还是空的"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"")
        return out_path


@pytest.mark.parametrize(
    ("mode", "label", "lines"),
    [
        ("full_narration", "全片解说", ("台词一", "台词二")),
        # 交叉解说的旁白段压在下一场景开头，首句台词落在全部区间之外
        ("cross_narration", "交叉解说", ("台词二",)),
    ],
)
def test_style_directives_reach_the_copy_prompt(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    label: str,
    lines: tuple[str, ...],
) -> None:
    """I2：口味层选出的风格指令必须真的进到语言层 prompt。

    此前全仓无人产出 `_style_directives`，语言层读侧的绿灯走的是测试手搓的那一行；
    本用例走生产入口 `_inject_run_settings` → `_generate_one`，中间任何一环断开都红。
    """
    project_id = _seed_project_with_analysis(memory_db, tmp_path, sample_video)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    context = harness.context
    context.settings.update(
        {
            "llm.base_url": "http://llm.test/v1",
            "llm.api_key": "sk-test",
            "llm.model": "test-model",
            "narration.style_id": "auto",
        }
    )
    _FakeLlm.calls = []
    monkeypatch.setattr(script_driver, "LlmClient", _FakeLlm)
    monkeypatch.setattr(copywriter, "LlmClient", _FakeLlm)
    monkeypatch.setattr(
        styles,
        "_load_builtin",
        lambda: {
            _PLANTED_STYLE_ID: {
                "style_id": _PLANTED_STYLE_ID,
                "name": "反问体",
                "desc": "全程反问推进",
                "directives": _PLANTED_DIRECTIVES,
            }
        },
    )
    monkeypatch.setattr(pipeline, "create_tts", lambda *a, **k: _StubTts())
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", lambda _p: 1.25)

    episodes = _done_episodes(memory_db, project_id)
    settings = dict(context.settings)
    episode_inputs = narration_api._inject_run_settings(context, settings, episodes)
    narration_api._generate_one(context, mode, episodes, episode_inputs, settings)

    copy_prompts = [user for system, user in _FakeLlm.calls if "风格库" not in system]
    assert len(copy_prompts) == 1, f"语言层应被调用一次，实得 {len(copy_prompts)}"
    prompt = copy_prompts[0]
    assert _PLANTED_DIRECTIVES in prompt, "口味层解析出的风格指令没进语言层 prompt"

    plan_row = narration_api._newest_ready_plan(context, project_id, mode)
    assert plan_row is not None
    plan_data = PlanData.model_validate(plan_row["plan_data"])
    assert plan_data.planner == "llm_script"
    slot_ids = [text.id for text in plan_data.narration_texts]
    assert slot_ids, f"{mode} 未产出任何槽位——本用例什么都没验"
    assert [text.text for text in plan_data.narration_texts] == [
        f"{slot_id} 的解说" for slot_id in slot_ids
    ], "落库文案与槽位 id 不对应"
    assert all(f"[{slot_id}] 要做的事：" in prompt for slot_id in slot_ids), "槽位未逐条进 prompt"
    assert all(line in prompt for line in lines), "素材台词未进 prompt"
    assert f"模式：{label}" in prompt, "模式标签未取自 pipeline.MODE_LABELS"


def test_dialogue_without_transcript_fails_loudly(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    """没有转写就没有编剧链的米：剧情解说整条方案失败，且不得凭空给出口味层结论。"""
    project_id = _seed_project_with_analysis(memory_db, tmp_path, sample_video)
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    analysis_repo.upsert(
        memory_db,
        episode_id,
        asr_segments="[]",
        scene_data="[]",
        audio_features=AudioFeatures().model_dump_json(),
    )
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    context = harness.context
    episodes = _done_episodes(memory_db, project_id)

    settings = dict(context.settings)
    episode_inputs = narration_api._inject_run_settings(context, settings, episodes)
    assert episode_inputs == []
    assert "_style_directives" not in settings, "无从选题时不该装作选了风格"
    with pytest.raises(ValueError, match="没有带转写的已完成集"):
        narration_api._generate_one(context, "dialogue_narration", episodes, [], settings)


def test_dialogue_unconfigured_llm_keeps_rule_fallback(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    """编剧链此刻仍会返回 None（未配置 LLM）：api 侧必须继续接得住，Task 5 才改抛。"""
    project_id = _seed_project_with_analysis(memory_db, tmp_path, sample_video)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    context = harness.context
    episodes = _done_episodes(memory_db, project_id)

    settings = dict(context.settings)
    episode_inputs = narration_api._inject_run_settings(context, settings, episodes)
    assert episode_inputs, "种子数据应当给出跨集输入，否则本用例什么都没走"
    narration_api._generate_one(context, "dialogue_narration", episodes, episode_inputs, settings)

    plan_row = narration_api._newest_ready_plan(context, project_id, "dialogue_narration")
    assert plan_row is not None
    plan_data = PlanData.model_validate(plan_row["plan_data"])
    assert plan_data.planner == "rule"
    assert plan_data.narration_texts == []
