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
from dramaclip.engines.semantic.llm_client import LlmUnavailable
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


def _wait_terminal(harness: Harness, job_id: str, timeout_s: float = 10.0) -> dict[str, Any]:
    """等任务进终态并返回最后一行；超时不抛。

    与 `Harness.wait_job` 的分工：那条路等的是成功，超时即 AssertionError("任务超时")，
    会把「卡在 running」这种症状报成一句看不出所以然的话。这里超时原样返回最后一行，
    让断言自己报出它还停在哪个状态。
    """
    deadline = time.time() + timeout_s
    status = harness.rpc("analysis.status", {"job_id": job_id})
    while time.time() < deadline and not jobs.is_terminal(str(status["status"])):
        time.sleep(0.05)
        status = harness.rpc("analysis.status", {"job_id": job_id})
    return status


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


@pytest.mark.parametrize(("mode", "expected_selections"), [("raw_clip", 0), ("full_narration", 1)])
def test_style_selection_only_paid_for_modes_that_narrate(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_selections: int,
) -> None:
    """没有任何模式会产出旁白槽位时，口味层答案无人可读——一次都不该付。

    重构前选题只发生在 `script_dialogue_plan` 内（即只有剧情解说付费）；任务级注入
    若无条件调用 `resolve_run_style`，`raw_clip` 这种纯剪辑作业就凭空多付一次 LLM
    往返，与「停止按模式付费」这次重构的初衷同类相反。

    一次作业一个 harness：`_generate_one` 被桩掉后作业必然以「编排结果缺失」失败，
    本题只数选题请求，终态由 `_wait_terminal` 兜住（不许卡在非终态报零次）。
    """
    project_id = _seed_project_with_analysis(memory_db, tmp_path, sample_video)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(
        {
            "llm.base_url": "http://llm.test/v1",
            "llm.api_key": "sk-test",
            "llm.model": "test-model",
            "narration.style_id": "auto",
        }
    )
    monkeypatch.setattr(script_driver, "LlmClient", _FakeLlm)
    # 编排与本题无关：桩掉它，选题次数才只由任务级注入决定。
    monkeypatch.setattr(narration_api, "_generate_one", lambda *_a, **_k: None)

    _FakeLlm.calls = []
    produce = harness.rpc("narration.produce", {"project_id": project_id, "modes": [mode]})
    status = _wait_terminal(harness, str(produce["job_id"]))
    assert jobs.is_terminal(str(status["status"])), f"作业未进终态：{status}"

    selections = sum(1 for system, _user in _FakeLlm.calls if "风格库" in system)
    assert selections == expected_selections, f"{mode} 付了 {selections} 次口味层选题"


def test_only_sound_only_modes_skip_tts_group() -> None:
    """分组只决定「谁可与配音并行」，两处代码完全同形，套件里再无第二处看得见这个集合。

    剧情解说在剧本链落地后每段都要配音，留在无 TTS 组等于宣称它没有旁白。
    """
    tts_free = frozenset({"raw_clip", "subtitle_flow"})
    assert tts_free == narration_api._NO_TTS_MODES


def test_every_supported_mode_has_a_chinese_label() -> None:
    """三处九模式镜像必须齐步走：入口清单与中文标签集一分家，队列页就露出英文模式名。

    `narration_api.SUPPORTED_MODES`（入口校验）/ `pipeline.MODE_LABELS`（人读标签）
    是本文件能到的两处；`desktop/src/components/modeMeta.ts` 的 `MODE_INFO` 是第三面
    镜子，service 侧够不着（已在计划里记为 P-3 已知接受项）。
    """
    assert set(pipeline.MODE_LABELS) == set(narration_api.SUPPORTED_MODES)


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
    episode_inputs = narration_api._inject_run_settings(context, settings, episodes, [mode])
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
    episode_inputs = narration_api._inject_run_settings(
        context, settings, episodes, ["dialogue_narration"]
    )
    assert episode_inputs == []
    assert "_style_directives" not in settings, "无从选题时不该装作选了风格"
    with pytest.raises(ValueError, match="没有带转写的已完成集"):
        narration_api._generate_one(context, "dialogue_narration", episodes, [], settings)


def test_pinned_style_survives_a_project_without_transcripts(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """用户手动钉死风格、全剧却没有转写：风格不能顺手被丢掉，也不能不发一语。

    转写只是 **AI 自选**风格的原料；`resolve_style_id(preferred, genre)` 对着钉死的
    风格 id 什么都不问。整段口味层装配被 `if episode_inputs` 一起跳过时，丢的既是
    用户的选择又是 `_style_log_line` 那句留痕。
    """
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
    context.settings["narration.style_id"] = _PLANTED_STYLE_ID
    _FakeLlm.calls = []
    monkeypatch.setattr(script_driver, "LlmClient", _FakeLlm)
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

    settings = dict(context.settings)
    episodes = _done_episodes(memory_db, project_id)
    episode_inputs = narration_api._inject_run_settings(
        context, settings, episodes, ["dialogue_narration"]
    )
    assert episode_inputs == [], "本用例要的就是没有转写，种子被改则什么都没验"
    assert settings.get("_style_directives") == _PLANTED_DIRECTIVES, "手动钉的风格被丢了"
    assert _FakeLlm.calls == [], "钉死风格无需选题，一次请求都不该发"


def test_dialogue_unconfigured_llm_fails_the_plan(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    """降级禁止：未配置 LLM 时剧情解说整条方案失败，不再退回规则编排那一版。"""
    project_id = _seed_project_with_analysis(memory_db, tmp_path, sample_video)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    context = harness.context
    episodes = _done_episodes(memory_db, project_id)

    settings = dict(context.settings)
    episode_inputs = narration_api._inject_run_settings(
        context, settings, episodes, ["dialogue_narration"]
    )
    assert episode_inputs, "种子数据应当给出跨集输入，否则本用例什么都没走"
    with pytest.raises(LlmUnavailable, match="引擎"):
        narration_api._generate_one(
            context, "dialogue_narration", episodes, episode_inputs, settings
        )


@pytest.mark.parametrize("method", ["narration.produce", "narration.generate_plans"])
def test_assembly_failure_lands_in_jobs_table(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    """任务级装配抛（RPC 检查后项目被删是真实路径）：三条可观察后果缺一不可。

    `_inject_run_settings` 在两个 runner 里都位于逐模式 try 之前，而
    `executor.submit` 不挂 done-callback（service_app.py:72/146），抛出没人接就是
    一行永远停在 running 的 jobs + 一个泄漏的 cancel_event——与本仓已中过两次的
    「没有 mark_running 的路径让行永停 pending」同一类。失败要抛得有人接。

    真删项目的用例要卡时序（job_id 已返回、worker 尚未跑），这里以桩代替：
    抛的就是那条 `项目不存在`。
    """
    project_id = _seed_project_with_analysis(memory_db, tmp_path, sample_video)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)

    def boom(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        raise ValueError("项目不存在: 装配期已被删除")

    monkeypatch.setattr(narration_api, "_inject_run_settings", boom)
    job_id = str(harness.rpc(method, {"project_id": project_id, "modes": ["raw_clip"]})["job_id"])

    status = _wait_terminal(harness, job_id)
    assert status["status"] == "failed", f"任务停在 {status['status']}，装配失败没人兜底"
    assert status["error"] == "项目不存在: 装配期已被删除"
    assert job_id not in harness.context.cancel_events, "cancel_events 未释放"


def test_produce_runner_raise_still_settles_the_job(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """渲染循环里、逐模式 try 之外抛出：作业仍须进终态，cancel_event 仍须释放。

    `notifier.progress` 那句就在保护圈外（`_run_produce` 的渲染段）：它一炸，
    没有 try/finally 的 runner 会把异常丢进 executor 的 future 里没人读，
    jobs 行永远停在 running、cancel_events 里永远挂着这个 job。
    """
    project_id = _seed_project_with_analysis(memory_db, tmp_path, sample_video)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("进度通知通道已断")

    monkeypatch.setattr(harness.context.notifier, "progress", boom)
    job_id = str(
        harness.rpc(
            "narration.produce", {"project_id": project_id, "modes": ["raw_clip"]}
        )["job_id"]
    )

    status = _wait_terminal(harness, job_id)
    assert jobs.is_terminal(str(status["status"])), f"作业停在 {status['status']}：抛出没人接"
    assert job_id not in harness.context.cancel_events, "cancel_events 未释放"


def test_generation_runner_raise_still_releases_cancel_event(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """落终态那一步抛出（末尾 pop 之前）：cancel_event 不能留在字典里。"""
    project_id = _seed_project_with_analysis(memory_db, tmp_path, sample_video)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    monkeypatch.setattr(narration_api, "_generate_one", lambda *_a, **_k: None)

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("jobs 表写不进去")

    monkeypatch.setattr(harness.context.job_store, "mark_completed", boom)
    job_id = str(
        harness.rpc(
            "narration.generate_plans", {"project_id": project_id, "modes": ["raw_clip"]}
        )["job_id"]
    )

    status = _wait_terminal(harness, job_id)
    assert jobs.is_terminal(str(status["status"])), f"作业停在 {status['status']}：抛出没人接"
    assert job_id not in harness.context.cancel_events, "cancel_events 未释放"


class _FullModeBrokenTts:
    """只对 full_narration 的槽位（id 前缀 `full-`）不可达：用来量失败粒度。"""

    def synthesize(self, text: str, _voice: str | None, out_path: Path) -> Path:
        if out_path.stem.startswith("full"):
            raise RuntimeError("云端不可达")
        assert text.strip(), "语言层没填上文案，槽位还是空的"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"")
        return out_path


def test_tts_failure_fails_one_mode_not_the_batch(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """失败粒度=单条方案：第二个模式配音缺件，第一个照样成稿并进入渲染。

    配音改成抛错之后，最容易顺手写坏的就是这层：异常一路冒出 `_run_produce`，
    整批作业中止，第一个模式明明已经出了片却在 jobs 里查无此人。
    """
    project_id = _seed_project_with_analysis(memory_db, tmp_path, sample_video)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    context = harness.context
    context.settings.update(
        {
            "llm.base_url": "http://llm.test/v1",
            "llm.api_key": "sk-test",
            "llm.model": "test-model",
            "narration.style_id": _PLANTED_STYLE_ID,
        }
    )
    _FakeLlm.calls = []
    monkeypatch.setattr(script_driver, "LlmClient", _FakeLlm)
    monkeypatch.setattr(copywriter, "LlmClient", _FakeLlm)
    monkeypatch.setattr(pipeline, "create_tts", lambda *a, **k: _FullModeBrokenTts())
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", lambda _p: 1.25)
    rendered: list[str] = []
    monkeypatch.setattr(
        narration_api,
        "render_export",
        lambda _ctx, run, report: rendered.append(run.plan_data.mode),
    )

    job = harness.rpc(
        "narration.produce",
        {"project_id": project_id, "modes": ["intro_narration", "full_narration"]},
    )
    status = _wait_terminal(harness, str(job["job_id"]))

    assert status["status"] == "failed", status
    error = str(status["error"])
    assert "全片解说" in error and "合成失败" in error, f"失败没点名到模式与原因：{error}"
    assert "片头解说" not in error, f"第一个模式被第二个的失败牵连了：{error}"
    assert rendered == ["intro_narration"], f"渲染只该跑成功的那条方案：{rendered}"
    assert narration_api._newest_ready_plan(context, project_id, "intro_narration") is not None
    assert narration_api._newest_ready_plan(context, project_id, "full_narration") is None
    assert str(job["job_id"]) not in context.cancel_events, "cancel_events 未释放"
