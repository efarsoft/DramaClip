"""作业归因与 LLM 留痕的接线面（立案C）。

实测缺口：8 个 LLM 调用点只有 3 个写 trace（缺选风格、冲突、题材、标题——恰是会悄悄
变差的四条）；log.append 无 job_id，并发作业下分不清哪条任务说的；渲染层根本没订
log.append，业务日志当场蒸发。引擎层行为见各自测试，这里只钉 api 层的接线。
"""

from __future__ import annotations

import ast
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import analysis as analysis_api
from dramaclip.api import export as export_api
from dramaclip.api import narration as narration_api
from dramaclip.engines.analysis.models import EpisodeRawAnalysis
from dramaclip.engines.semantic.llm_client import LlmClient
from dramaclip.infra import jobs as jobs_mod
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import Router, RpcRequest
from tests.api.test_export_submit import _seed_plan, _voiced_plan
from tests.api.test_plan_variants import _LLM_SETTINGS

_API_ROOT = Path(__file__).resolve().parents[2] / "dramaclip" / "api"

# 会悄悄变差的四条：LLM 一降级，接口返回值照样"看着对"，只有往返文件能解释。
_TRACE_KWARG = {
    "enhance": "trace_dir",
    "resolve_run_style": "trace_dir",
    "select_angles": "trace_dir",
    "script_dialogue_plan": "trace_dir",
    "generate": "trace_path",
}

_REPLIES: dict[str, Any] = {
    "短剧剪辑顾问": [{"scene_index": 0, "score": 92, "reason": "当众羞辱"}],
    "短剧发行顾问": {"genre": "复仇"},
    "短剧推广策略师": {"style_id": "shuanggan", "reason": "打脸爽点密"},
    "短剧推广视频标题专家": {"titles": ["她当众揭穿未婚夫"]},
}


class SyncExecutor:
    """同步执行任务体：RPC 返回即任务已跑完，不必轮询终态。"""

    def submit(self, fn: Any) -> None:
        fn()


def _harness(
    memory_db: sqlite3.Connection, tmp_path: Path, *modules: Any
) -> SimpleNamespace:
    sent: list[dict[str, Any]] = []
    context = SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "cache",
        settings=dict(_LLM_SETTINGS),
        notifier=Notifier(sent.append),
        executor=SyncExecutor(),
        job_store=jobs_mod.JobStore(memory_db),
        analysis_runtime=SimpleNamespace(transcriber=lambda: None),
        cancel_events={},
    )
    router = Router()
    for module in modules:
        module.register(router, context)  # type: ignore[arg-type]
    return SimpleNamespace(context=context, router=router, sent=sent)


def _rpc(harness: SimpleNamespace, method: str, params: dict[str, Any]) -> Any:
    response = harness.router.dispatch(RpcRequest(id=method, method=method, params=params))
    if response.error is not None:
        raise AssertionError(f"{method} RPC 错误: [{response.error.code}] {response.error.message}")
    return response.result


def _seed(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    *,
    status: str = "pending",
    analyzed: bool = False,
) -> tuple[str, str]:
    """一个项目一集（可选直种分析记录），返回 (project_id, episode_id)。"""
    project_id = str(projects_repo.create(memory_db, "归因剧", str(tmp_path))["id"])
    episodes_repo.replace_all(
        memory_db, project_id, [{"episode_number": 1, "source_path": str(tmp_path / "e1.mp4"),
                                 "duration": 40.0}]
    )
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    episodes_repo.set_status(memory_db, episode_id, status)
    if analyzed:
        analysis_repo.upsert(
            memory_db,
            episode_id,
            asr_segments=json.dumps(
                [
                    {"start": 0.2, "end": 0.8, "text": "她跪在雨里求他"},
                    {"start": 1.0, "end": 1.6, "text": "他当众揭穿了婚约"},
                ]
            ),
            scene_data=json.dumps(
                [{"scene_index": 0, "start": 0.0, "end": 2.0, "score": 60}]
            ),
            audio_features="{}",
            conflict_scores="[]",
            highlights="[]",
        )
    return project_id, episode_id


def _logs(sent: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item["params"] for item in sent if item["method"] == "log.append"]


def _probe(context: Any, job_id: str, *rest: Any) -> None:
    """任务体替身：只在作业作用域里说一句话，用来验归因。"""
    context.notifier.log("info", f"任务体执行于 {job_id}")


def _stub_chat_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(self: LlmClient, system: str, user: str) -> Any:
        for marker, reply in _REPLIES.items():
            if marker in system:
                return reply
        raise AssertionError(f"未预期的 LLM 调用：{system[:40]}")

    monkeypatch.setattr(LlmClient, "chat_json", fake)


def _traces(tmp_path: Path) -> dict[str, dict[str, Any]]:
    trace_dir = tmp_path / "logs" / "llm"
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(trace_dir.glob("llm_*.json"))
    }


# ── 作业归因：五处投池站点，日志必须说得出属于哪条任务 ──────────────────────


def test_prescreen_logs_carry_the_job_id(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(memory_db, tmp_path, analysis_api)
    monkeypatch.setattr(analysis_api, "_run_prescreen", _probe)
    project_id, _episode_id = _seed(memory_db, tmp_path)

    job_id = str(_rpc(harness, "analysis.prescreen", {"project_id": project_id})["job_id"])
    assert [item["job_id"] for item in _logs(harness.sent)] == [job_id]
    # 出了作业作用域就不该再挂着上一个任务号：线程池复用工作线程
    harness.context.notifier.log("info", "作用域外")
    assert "job_id" not in _logs(harness.sent)[-1]


def test_start_logs_carry_the_job_id(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(memory_db, tmp_path, analysis_api)
    monkeypatch.setattr(analysis_api, "_run_job", _probe)
    project_id, _episode_id = _seed(memory_db, tmp_path)

    job_id = str(_rpc(harness, "analysis.start", {"project_id": project_id})["job_id"])
    assert [item["job_id"] for item in _logs(harness.sent)] == [job_id]


def test_resync_logs_carry_the_job_id(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(memory_db, tmp_path, analysis_api)
    monkeypatch.setattr(analysis_api, "_run_resync", _probe)
    project_id, episode_id = _seed(memory_db, tmp_path, status="done", analyzed=True)

    job_id = str(
        _rpc(
            harness,
            "analysis.resync_semantic",
            {"project_id": project_id, "episode_id": episode_id},
        )["job_id"]
    )
    assert [item["job_id"] for item in _logs(harness.sent)] == [job_id]


def test_plan_variants_logs_carry_the_job_id(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(memory_db, tmp_path, narration_api)
    monkeypatch.setattr(narration_api, "_run_plan_variants", _probe)
    project_id, _episode_id = _seed(memory_db, tmp_path, status="done", analyzed=True)

    job_id = str(
        _rpc(
            harness,
            "narration.plan_variants",
            {"project_id": project_id, "modes": ["full_narration"], "k": 1},
        )["job_id"]
    )
    assert [item["job_id"] for item in _logs(harness.sent)] == [job_id]


def test_export_logs_carry_the_job_id(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(memory_db, tmp_path, export_api)
    monkeypatch.setattr(export_api, "_run_export", _probe)
    _project_id, plan_id = _seed_plan(memory_db, tmp_path, _voiced_plan(tmp_path))

    result = _rpc(harness, "export.submit", {"plan_ids": [plan_id]})
    job_id = str(result["exports"][0]["job_id"])
    assert [item["job_id"] for item in _logs(harness.sent)] == [job_id]


# ── 留痕：四条会悄悄变差的调用，往返要落回 data_dir/logs/llm ──────────────────


def test_resync_semantic_leaves_conflict_and_genre_traces(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(memory_db, tmp_path, analysis_api)
    _stub_chat_json(monkeypatch)
    project_id, episode_id = _seed(memory_db, tmp_path, status="done", analyzed=True)

    _rpc(
        harness,
        "analysis.resync_semantic",
        {"project_id": project_id, "episode_id": episode_id},
    )
    traces = _traces(tmp_path)
    conflict = traces.get(f"llm_conflict_{episode_id}.json")
    genre = traces.get(f"llm_genre_{episode_id}.json")
    assert conflict is not None, f"冲突打分未留痕：{sorted(traces)}"
    assert conflict["raw"] == _REPLIES["短剧剪辑顾问"]
    assert conflict["degraded"] is False and conflict["missing_scenes"] == 0
    assert genre is not None, f"题材分类未留痕：{sorted(traces)}"
    assert genre["matched"] is True and genre["model_genre"] == "复仇"


def test_start_job_leaves_conflict_and_genre_traces(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """出片主线（逐集分析）同样要留痕：真机「高光不疼」多半就差这一步证据。"""
    harness = _harness(memory_db, tmp_path, analysis_api)
    _stub_chat_json(monkeypatch)
    project_id, episode_id = _seed(memory_db, tmp_path)
    raw = EpisodeRawAnalysis(
        asr_segments=[{"start": 0.2, "end": 0.8, "text": "他当众揭穿了婚约！"}],
        scenes=[{"scene_index": 0, "start": 0.0, "end": 2.0, "score": 60}],
        audio={},
    )
    monkeypatch.setattr(analysis_api.pipeline, "analyze_episode", lambda **_kw: raw)
    monkeypatch.setattr(analysis_api, "_mine_hotwords", lambda *_a, **_k: ({}, {}, {}, ""))
    monkeypatch.setattr(analysis_api, "_fuse_ocr", lambda *_a, **_k: ([], None, None, None))

    _rpc(harness, "analysis.start", {"project_id": project_id})
    traces = _traces(tmp_path)
    assert f"llm_conflict_{episode_id}.json" in traces, sorted(traces)
    assert f"llm_genre_{episode_id}.json" in traces, sorted(traces)


def test_style_selection_leaves_a_trace(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(memory_db, tmp_path, narration_api)
    _stub_chat_json(monkeypatch)
    project_id, episode_id = _seed(memory_db, tmp_path, status="done", analyzed=True)
    episodes = episodes_repo.list_by_ids(memory_db, [episode_id])
    settings: dict[str, str] = dict(_LLM_SETTINGS)
    settings["narration.style_id"] = "auto"

    narration_api._inject_run_settings(harness.context, settings, episodes, ["full_narration"])
    blobs = _traces(tmp_path)
    names = [name for name in blobs if name.startswith("llm_style_select_")]
    assert len(names) == 1, f"口味层选题未留痕：{sorted(blobs)}"
    blob = blobs[names[0]]
    assert blob["engine"] == "style_select" and blob["accepted"] is True
    assert blob["style_id"] == "shuanggan"
    assert settings["_style_directives"], "选中的风格没有进入口味层"


def test_generate_titles_leaves_a_trace(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(memory_db, tmp_path, narration_api)
    _stub_chat_json(monkeypatch)
    _project_id, plan_id = _seed_plan(memory_db, tmp_path, _voiced_plan(tmp_path))

    titles = _rpc(harness, "narration.generate_titles", {"plan_id": plan_id})["titles"]
    assert titles[0]["text"] == "她当众揭穿未婚夫"
    blob = _traces(tmp_path).get(f"llm_titles_{plan_id}.json")
    assert blob is not None, f"候选标题未留痕：{sorted(_traces(tmp_path))}"
    assert blob["raw"] == _REPLIES["短剧推广视频标题专家"] and blob["accepted"] == 1


# ── 永久守卫：api 层调进 LLM 的每一处都必须给出留痕落点 ─────────────────────


def test_every_api_llm_call_site_passes_a_trace_target() -> None:
    """漏传一个 trace 参数＝那条链路重新变成"坏了也不知道为什么坏"。

    按 AST 而非文本比对：注释、字符串里的同名片段不算数。
    """
    missing: list[str] = []
    for py in sorted(_API_ROOT.glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            wanted = _TRACE_KWARG.get(node.func.attr)
            if wanted is None:
                continue
            if not any(keyword.arg == wanted for keyword in node.keywords):
                missing.append(f"{py.name}:{node.lineno} {node.func.attr}()")
    assert missing == [], f"以下 LLM 调用点未接留痕落点: {missing}"
