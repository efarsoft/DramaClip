"""narration.plan_variants / export.submit：规划与渲染拆开后的端到端（确定性数据直种）。"""

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
from dramaclip.engines.narration import (
    angles,
    copywriter,
    overlap,
    pipeline,
    script_driver,
    styles,
)
from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    TimelineSegment,
)
from dramaclip.infra import jobs
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import plans as plans_repo
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
    """与 plan_variants 入口同口径：只取分析完成的集。"""
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
def test_pinned_style_survives_a_project_without_transcripts(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    label: str,
    lines: tuple,
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


def test_assembly_failure_lands_in_jobs_table(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    job_id = str(harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["raw_clip"], "k": 1},
    )["job_id"])

    status = _wait_terminal(harness, job_id)
    assert status["status"] == "failed", f"任务停在 {status['status']}，装配失败没人兜底"
    assert status["error"] == "项目不存在: 装配期已被删除"
    assert job_id not in harness.context.cancel_events, "cancel_events 未释放"


def _variant_plan(copy_prefix: str) -> PlanData:
    """同模式同槽位 id、只有文案不同：内容寻址要隔离的东西。"""
    return PlanData(
        mode="full_narration",
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=0.0, end=2.0, audio="ducked", narration_id="full-1"
            )
        ],
        narration_texts=[
            NarrationText(id="full-1", text=f"{copy_prefix}·第一段解说", brief="推进")
        ],
    )


class _TextWritingTts:
    """把文案原样写进音频文件：读内容即知这是谁的音。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def synthesize(self, text: str, _voice: str | None, out_path: Path) -> Path:
        assert text.strip(), "语言层没填上文案"
        self.calls.append(text)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(text.encode("utf-8"))
        return out_path


def test_voice_gives_each_variant_its_own_audio(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_voice` 是 plan_variants 唯一的配音出口，它给出的目录让内容寻址照常生效。

    **本用例不是 test_tts_audio_isolation.py 的重复**：那六例守的是 pipeline 层
    （文件名怎么算、缓存怎么判、失败怎么清），本用例守的是 **api 层到 pipeline 的接线**——
    `_voice` 传错目录、传错 models_dir、或者干脆忘了调 synthesize_narration_texts，
    那六例一条都不会红。断言读**文件内容**而不是比路径，理由同上。
    """
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    engine = _TextWritingTts()
    monkeypatch.setattr(pipeline, "create_tts", lambda *a, **k: engine)
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", lambda _p: 1.25)
    settings = dict(harness.context.settings)

    voiced = [
        narration_api._voice(harness.context, _variant_plan(prefix), settings)
        for prefix in ("角度一", "角度二")
    ]

    assert len(engine.calls) == 2, f"两条方案各一次配音，实得 {engine.calls}"
    for plan in voiced:
        text = plan.narration_texts[0]
        assert text.audio_path, "配音后 audio_path 仍是空的"
        content = Path(text.audio_path).read_text(encoding="utf-8")
        assert content == text.text, (
            f"audio_path 指向的不是这条方案自己的音：内容={content!r}，应为={text.text!r}"
        )
    first_path = voiced[0].narration_texts[0].audio_path
    second_path = voiced[1].narration_texts[0].audio_path
    assert first_path != second_path, "文案不同却落在同一路径——内容寻址没生效"


def test_voice_keeps_the_cross_call_cache(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """文案相同的槽位只合成一次：`_voice` 的目录**不得随调用变化**。

    这条用例是"不要给 tts 目录加作业号/变体号/随机数"的唯一自动化守卫。加进去之后
    路径仍然互异（所以上面那条隔离用例照样绿），但 pipeline 的缓存优先
    （docs/service/02 §6、test_tts_audio_isolation.py::test_identical_copy_is_synthesised_once）
    在 api 层就失效了：整组重规划与「重掷此条」都会为**没改过的槽位**再付一次配音。
    """
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    engine = _TextWritingTts()
    monkeypatch.setattr(pipeline, "create_tts", lambda *a, **k: engine)
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", lambda _p: 1.25)
    settings = dict(harness.context.settings)

    first = narration_api._voice(harness.context, _variant_plan("同一份文案"), settings)
    calls_after_first = len(engine.calls)
    second = narration_api._voice(harness.context, _variant_plan("同一份文案"), settings)

    assert calls_after_first == 1
    assert len(engine.calls) == 1, "第二次调用又付了一遍配音：目录随调用变化了"
    assert second.narration_texts[0].audio_path == first.narration_texts[0].audio_path

def _seed_project_with_episodes(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    count: int,
) -> str:
    """建项目 + count 集，每集直种**时间区间互不相交**的分析数据，全部标 done。

    集与集的场景时间刻意错开（第 i 集从 100*i 秒起）：这样「两条角度取不同集」的
    取材重叠恒为 0，用例才不必去猜编排器会挑中哪几段。**注意这与生产形状相反**——
    活库实测十集的场景起点全部从 0.0 开始，集与集的秒轴互相覆盖；错开是为了让
    `overlap` 的读数可预期，跨集秒轴重合那条性质由 `test_casting.py` 与
    `test_cross_episode_arrangement.py` 在引擎层单独钉。
    源文件是同一个 sample_video 复制 count 份——本种子只服务规划路径，不渲染。
    """
    for index in range(1, count + 1):
        import shutil

        shutil.copy(sample_video, tmp_path / f"ep{index}.mp4")
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    project = harness.rpc("project.create", {"name": "多集剧", "source_path": str(tmp_path)})
    harness.rpc("project.scan_episodes", {"project_id": project["id"]})
    project_id = str(project["id"])
    for episode in episodes_repo.list_by_project(memory_db, project_id):
        number = int(episode["episode_number"])
        offset = 100.0 * number
        scenes = [
            {
                "scene_index": i,
                "start": offset + i * 10.0,
                "end": offset + i * 10.0 + 8.0,
                "score": 40 + i * 15,
            }
            for i in range(3)
        ]
        analysis_repo.upsert(
            memory_db,
            str(episode["id"]),
            asr_segments=json.dumps(
                [
                    {"start": offset + 0.2, "end": offset + 3.0, "text": f"第 {number} 集台词一"},
                    {"start": offset + 4.0, "end": offset + 7.0, "text": f"第 {number} 集台词二"},
                ]
            ),
            scene_data="[]",
            audio_features=AudioFeatures().model_dump_json(),
            conflict_scores=json.dumps(scenes),
            highlights=json.dumps(
                [
                    {
                        "scene_index": 2,
                        "start": offset + 20.0,
                        "end": offset + 28.0,
                        "score": 64,
                        "reason": "冲突",
                    }
                ]
            ),
        )
        episodes_repo.set_status(memory_db, str(episode["id"]), "done")
    return project_id


def _stub_language_and_tts(
    monkeypatch: pytest.MonkeyPatch, llm_calls: list[tuple[str, str]]
) -> None:
    """选题、成稿、配音三处替身：规划路径的端到端用例不该等真 LLM 与真 TTS。"""

    class _Llm:
        def __init__(self, _config: Any, timeout_s: float = 60.0) -> None:
            self.timeout_s = timeout_s

        def chat_json(self, system: str, user: str) -> Any:
            llm_calls.append((system, user))
            if "选题操盘手" in system:  # angles._SYSTEM_PROMPT
                wanted = int(re.search(r"需要 (\d+) 条", user).group(1))  # type: ignore[union-attr]
                # 遵守排除指令：被「重掷此条」排除的角度名不再提出（真模型理应如此，
                # 静态替身必须同样遵守，否则 test_exclude_plan_ids 的第一次尝试就会
                # 触发重试、选题 prompt 计数变成 2）。
                excluded: list[str] = []
                marker = "已存在、不得重复的角度："
                if marker in user:
                    tail = user.split(marker, 1)[1].splitlines()[0]
                    excluded = [n.strip() for n in tail.split("、") if n.strip()]
                # 每条角度给**两集、且各条互不相交**（{1,2} / {3,4} / {5,6}）：
                # ① 每条方案因此真的是跨集（规格 §1），用例才测得到裁决要的东西；
                # ② 互不相交 ⇒ 取材重叠恒为 0，`overlap_max == 0.0` 那条断言才成立；
                # ③ 各条的集组合互不相同 ⇒ 成稿前那道 `_reject_same_episode_sibling`
                #    不会误拦。**这三条一起要求种子至少 2K 集**，故本文件的种子是 6 集。
                names: list[str] = []
                i = 0
                while len(names) < wanted:
                    i += 1
                    candidate = f"角度{i}"
                    if candidate not in excluded:
                        names.append(candidate)
                return {
                    "angles": [
                        {
                            "name": name,
                            "reason": f"第 {2 * idx - 1}、{2 * idx} 集这条线最狠",
                            "hook": f"第 {2 * idx - 1} 集的开场钩子",
                            "episode_numbers": [2 * idx - 1, 2 * idx],
                        }
                        for idx, name in enumerate(names, start=1)
                    ]
                }
            if "风格库" in system:  # styles._SELECT_SYSTEM_PROMPT
                return {"style_id": "shuanggan", "reason": "全剧靠反问推进"}
            slots = re.findall(r"^\[([^\]]+)\] 要做的事：", user, flags=re.MULTILINE)
            return {"lines": [{"id": slot, "text": f"{slot} 的解说"} for slot in slots]}

    monkeypatch.setattr(angles, "LlmClient", _Llm)
    monkeypatch.setattr(copywriter, "LlmClient", _Llm)
    monkeypatch.setattr(script_driver, "LlmClient", _Llm)
    monkeypatch.setattr(pipeline, "create_tts", lambda *a, **k: _StubTts())
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", lambda _p: 1.25)


_LLM_SETTINGS = {
    "llm.base_url": "http://llm.test/v1",
    "llm.api_key": "sk-test",
    "llm.model": "test-model",
}


def test_plan_variants_writes_k_plans_without_rendering(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """出口判据本身：阶段③ 只看方案不渲染——K 条方案落库，一条 export 记录都不建。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 3},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "completed", status.get("error")
    assert result["k"] == 3 and result["batch_id"] == result["job_id"]

    plans = plans_repo.list_by_batch(memory_db, project_id, str(result["batch_id"]))
    assert len(plans) == 3
    assert [row["variant_index"] for row in plans] == [1, 2, 3]
    assert [row["angle"] for row in plans] == ["角度1", "角度2", "角度3"]
    assert all(row["angle_reason"] for row in plans)
    assert plans[0]["overlap_max"] is None, "首条没有兄弟，重叠率是「无从比」"
    assert all(row["overlap_max"] == 0.0 for row in plans[1:]), "三集互异取材，重叠应为 0"
    assert len({tuple(row["episode_ids"]) for row in plans}) == 3, "三条角度取的是同一集"

    assert harness.rpc("export.list", {"project_id": project_id}) == [], (
        "规划阶段不得建任何出片记录——那正是 produce 时代的病"
    )
    for row in plans:
        plan = PlanData.model_validate(row["plan_data"])
        assert plan.planner == "llm_script"
        assert all(text.audio_path for text in plan.narration_texts), "方案落库时必须已配音"

    selection_calls = sum(1 for system, _user in calls if "选题操盘手" in system)
    assert selection_calls == 1, f"选题应每模式一次，实得 {selection_calls} 次"


def test_one_mode_failure_does_not_kill_other_modes(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """选题失败只带走它自己那个模式的 K 条，其余模式照常出方案。

    记账口径：选题失败按 K 条记，否则界面会把「这个模式的 K 条全没了」
    显示成「这个模式本来就没有方案」。

    **模式对刻意选成一个解说类 + 一个规则类**（`full_narration` + `raw_clip`）：
    这正是 B2/R1 的回归形状——两族不同源（《定案四》），一族在选题上炸了，
    另一族既不该被牵连、也不该被拖去调 LLM。原计划用这一条同时验两件事，
    但没写明，故这里把意图钉进 docstring。
    """
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    real_select = angles.select_angles

    def select_except_full(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("mode_label") == "全片解说":
            raise ValueError("选题未产出 3 条合格角度：网关 502")
        return real_select(*args, **kwargs)

    monkeypatch.setattr(angles, "select_angles", select_except_full)

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration", "raw_clip"], "k": 3},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "failed", status
    error = str(status["error"])
    assert error.count("全片解说") == 3, f"选题失败应按 K 条记账，实得：{error}"
    assert "纯原片剪辑" not in error, f"规则类被解说类的选题失败牵连了：{error}"

    plans = plans_repo.list_by_batch(memory_db, project_id, str(result["batch_id"]))
    assert {row["narration_mode"] for row in plans} == {"raw_clip"}, "另一个模式被牵连了"
    assert len(plans) == 3
    assert all(row["angle"] == "" for row in plans), "规则类没有模型选的卖点角度"


def test_rejected_angle_does_not_pay_for_copy(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R7：同一组取材集的两条角度，其重叠闸门必须排在**成稿之前**，否则被拦的白付一次 LLM。

    可判定性是证明出来的、不是猜的：`_plan_one` 的非剧本分支里，角度只进
    `copywriter` 的 `angle_block`，**不进 `build_plan`**——
    `build_plan(mode, scenes, highlights, material, settings)`
    五个入参没有一个来自角度名或理由，而 `scenes`/`material` 都由 `_casting_for`
    从 `variant.episode_numbers` 确定性装配。故时间轴是 `(mode, 取材集组合)` 的纯函数，
    同一组集 ⇒ 同一条时间轴 ⇒ Jaccard = 1.0，成稿前就该判得出来。

    成稿调用数按 copywriter 的 system prompt 认（`_SYSTEM_PROMPT` 首句是
    「你是短剧推广解说编剧」），与选题（「选题操盘手」）、口味层（「风格库」）三者互不混淆。
    """
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    # 三条角度全指向第 1 集：与 test_overlapping_angle_is_dropped_not_stored 同一夹具，
    # 但这条用例量的是**成稿次数**，不是错误文案
    monkeypatch.setattr(
        angles,
        "select_angles",
        lambda *a, **k: [
            angles.AngleBrief(
                name=f"角度{i}", reason=f"理由{i}", hook=f"钩子{i}", episode_numbers=[1]
            )
            for i in (1, 2, 3)
        ],
    )

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 3},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "failed", status
    copy_calls = sum(1 for system, _user in calls if "解说编剧" in system)
    assert copy_calls == 1, (
        f"被拦的两条角度仍各付了一次成稿，实得 {copy_calls} 次（应为 1）——"
        "闸门排在成稿之后，那笔钱在库里也无从重算"
    )


def test_unknown_episode_in_a_brief_fails_only_that_variant(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_casting_for` 的缺号分支：点名集不在已完成集里就抛，绝不悄悄换一集顶上。

    这条用例是 Task 6 Step 10 变异 #10 的唯一守卫。没有它，把 `_casting_for` 的
    raise 改成"只用点得到的那几集"（或退回 `episodes[0]`）全套照绿——而那正是
    「K 条其实是同一部片切 K 次」的根源之一（每条角度都被悄悄换成同一批集）。
    **跨集之后这条分支的语义从"换一集"变成"少一集"**，两种都禁止：一次点名**全部**
    缺号再抛，运维才知道要补哪几集，而不是补完一集再炸一集。
    """
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    monkeypatch.setattr(
        angles,
        "select_angles",
        lambda *a, **k: [
            angles.AngleBrief(
                name="角度1", reason="理由1", hook="钩子1", episode_numbers=[1]
            ),
            angles.AngleBrief(
                name="角度2", reason="理由2", hook="钩子2", episode_numbers=[99]
            ),
        ],
    )

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 2},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "failed", status
    error = str(status["error"])
    assert "全片解说·角度2:" in error and "不在已完成分析的集里" in error, error
    assert "全片解说·角度1:" not in error, f"兄弟变体被牵连了：{error}"
    plans = plans_repo.list_by_batch(memory_db, project_id, str(result["batch_id"]))
    assert [row["angle"] for row in plans] == ["角度1"], "只有点名越界那条不该落库"


def test_named_episode_without_an_analysis_row_fails_only_that_variant(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """角度点名的集**没有 `episode_analysis` 行**：抛，点名到集号，不牵连兄弟（Step 10 #10b）。

    生产上这一支被 `angles._sanitize` 挡在前面（它的 `known_numbers` 取自 `episode_inputs`，
    而没有分析行的集进不了 `episode_inputs`——`_collect_episode_inputs` 对 `record is None`
    直接 `continue`）。**所以本用例桩掉选题**，验的是 `_casting_for` 自己那一层：两层守卫
    不能只留一层，否则哪天放宽 `_sanitize`（例如允许点名"分析失败的集"以便界面解释原因），
    `_plan_one` 就会拿不到素材、在编排器里出一个空时间轴，报出来的却是"没有可用素材"——
    看不出真因是缺分析行，而规格 §3.3.1 要求的是**点名到集号**的响亮失败。
    """
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    ep2 = str(
        next(
            episode["id"]
            for episode in episodes_repo.list_by_project(memory_db, project_id)
            if int(episode["episode_number"]) == 2
        )
    )
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)
    monkeypatch.setattr(
        angles,
        "select_angles",
        lambda *a, **k: [
            angles.AngleBrief(name="角度1", reason="理由1", hook="钩子1", episode_numbers=[1]),
            angles.AngleBrief(name="角度2", reason="理由2", hook="钩子2", episode_numbers=[2]),
        ],
    )

    real_get = analysis_repo.get

    def get_without_episode_2(conn: sqlite3.Connection, episode_id: str) -> Any:
        """只让第 2 集的分析行消失：其余集照常，兄弟变体才有机会证明自己没被牵连。"""
        return None if episode_id == ep2 else real_get(conn, episode_id)

    monkeypatch.setattr(analysis_repo, "get", get_without_episode_2)

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 2},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "failed", status
    error = str(status["error"])
    assert "全片解说·角度2:" in error and "第 2 集分析记录缺失" in error, error
    assert "全片解说·角度1:" not in error, f"兄弟变体被牵连了：{error}"
    plans = plans_repo.list_by_batch(memory_db, project_id, str(result["batch_id"]))
    assert [row["angle"] for row in plans] == ["角度1"], "只有缺分析行那条不该落库"


def test_episode_ids_come_from_the_timeline_not_the_brief(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """落库的 `episode_ids` 从**建好的时间轴**反推，不抄角度点名的那份（Step 10 #16）。

    卡片四要素之一是「取材集区间」（规格 §4.3），而它的数据源就是这一列。抄点名会把
    一集**一帧都没出现**的集列上去——规格 §9.5 的假文案类，且肉眼查不出来
    （成片看着正常，卡片上多写了一集）。

    夹具是"第 2 集分析过但一个冲突场景都没出"；**生产上不必这么构造**：活库实测
    `intro_narration` 一手点了 4 集 `[2,5,6,9]`、时间轴上只出现 2 集（ep2、ep5），
    因为 `_fit_duration` 按播出序填充、270s 的预算在 ep5 就用完了（Task 3c Step 8 的实测表）。
    同一个口径 `script_driver.script_dialogue_plan` 早就在用（它的 `used_ids` 逐字是
    `sorted({seg.episode_id for seg in plan.timeline})`，`script_driver.py:113`）。

    顺带钉住允许级降级的留痕（规格 §3.3）：取不到某一集的画面不是失败，但必须说一声。
    """
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    number_to_id = {
        int(episode["episode_number"]): str(episode["id"])
        for episode in episodes_repo.list_by_project(memory_db, project_id)
    }
    # 第 2 集：分析行在、冲突场景表为空（analysis_repo.upsert 是整行覆盖，故原地重种一次）
    analysis_repo.upsert(
        memory_db,
        number_to_id[2],
        asr_segments=json.dumps([{"start": 200.2, "end": 203.0, "text": "第二集台词"}]),
        scene_data="[]",
        audio_features=AudioFeatures().model_dump_json(),
        conflict_scores="[]",
        highlights="[]",
    )
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)
    monkeypatch.setattr(
        angles,
        "select_angles",
        lambda *a, **k: [
            angles.AngleBrief(
                name="角度1", reason="理由1", hook="钩子1", episode_numbers=[1, 2]
            )
        ],
    )

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 1},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "completed", status.get("error")

    plans = plans_repo.list_by_batch(memory_db, project_id, str(result["batch_id"]))
    assert len(plans) == 1
    timeline = PlanData.model_validate(plans[0]["plan_data"]).timeline
    assert {segment.episode_id for segment in timeline} == {number_to_id[1]}, (
        "夹具前提塌了：第 2 集没有冲突场景，时间轴上不该出现它"
    )
    assert plans[0]["episode_ids"] == [number_to_id[1]], (
        f"episode_ids 抄了角度点名的两集，卡片会列一集没出现的集：{plans[0]['episode_ids']}"
    )
    logged = [str(item) for item in harness.sent]
    assert any("第 2 集没有冲突场景" in item for item in logged), (
        f"取不到某一集的画面却没留痕（规格 §3.3）：{harness.sent}"
    )


def test_post_copy_overlap_gate_still_guards_cross_episode_modes(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """成稿**之后**那道重叠闸门不能被前置闸门取代：生产上 `dialogue_narration` 只剩它。

    前置闸门按集号判，所以它拦不住"取材集互异、画面却几乎重合"这一类——跨集模式的剧本
    由模型按角度现写，正是这一类（成稿前无从判定，只有事后量得到）。本用例**不真跑跨集模式**
    （那要等真 LLM 写剧本，慢且不确定），而是用度量替身把重叠钉成 0.9、并让两条角度取不同集，
    于是前置闸门必然不触发、红的必然是成稿后那一道。
    **没有这条用例，Task 6 Step 10 的变异 #3 就再也红不了**（前置闸门会顶包）。
    """
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    monkeypatch.setattr(overlap, "overlap", lambda _left, _right: 0.9)
    monkeypatch.setattr(
        angles,
        "select_angles",
        lambda *a, **k: [
            angles.AngleBrief(
                name=f"角度{i}", reason=f"理由{i}", hook=f"钩子{i}", episode_numbers=[i]
            )
            for i in (1, 2)
        ],
    )

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 2},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "failed", status
    error = str(status["error"])
    assert "全片解说·角度2:" in error and "重叠 90%" in error, error
    assert "全片解说·角度1:" not in error, f"首条没有兄弟，不该被拦：{error}"
    plans = plans_repo.list_by_batch(memory_db, project_id, str(result["batch_id"]))
    assert [row["angle"] for row in plans] == ["角度1"]
    copy_calls = sum(1 for system, _user in calls if "解说编剧" in system)
    assert copy_calls == 2, (
        f"跨集模式成稿前判不了重叠，两条都该付成稿——实得 {copy_calls} 次；"
        "若为 1，说明前置闸门被错误地扩到了 dialogue_narration 之外"
    )


def test_overlapping_angle_is_dropped_not_stored(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """取材重叠超 60% 的角度当场不出（规格 §4.3）：不落库、点名到撞了谁。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    # 三条角度全指向第 1 集：取材必然完全相同，后两条该被重叠度量拦下
    monkeypatch.setattr(
        angles,
        "select_angles",
        lambda *a, **k: [
            angles.AngleBrief(
                name=f"角度{i}", reason=f"理由{i}", hook=f"钩子{i}", episode_numbers=[1]
            )
            for i in (1, 2, 3)
        ],
    )

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 3},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "failed", status
    error = str(status["error"])
    assert "全片解说·角度2:" in error and "重叠" in error and "100%" in error, error
    assert "全片解说·角度3:" in error, f"第三条也该被拦（它与首条同样取材）：{error}"
    # 断言用「标签+冒号」而不是裸角度名：失败串是 "全片解说·角度2: 取材与「角度1」重叠 100%…"，
    # 里面**必然**出现"角度1"（它点的是撞了谁）。裸名断言会假红。
    assert "全片解说·角度1:" not in error, f"首条不该被拦：{error}"

    plans = plans_repo.list_by_batch(memory_db, project_id, str(result["batch_id"]))
    assert [row["angle"] for row in plans] == ["角度1"], "被拦的角度不该落库"


def test_exclude_plan_ids_reaches_the_selection_prompt(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """重掷此条：被排除方案的角度名必须进选题 prompt，否则模型会再提同一个卖点。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    first = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 1},
    )
    _wait_terminal(harness, str(first["job_id"]))
    plans = plans_repo.list_by_batch(memory_db, project_id, str(first["batch_id"]))
    assert len(plans) == 1

    calls.clear()
    reroll = harness.rpc(
        "narration.plan_variants",
        {
            "project_id": project_id,
            "modes": ["full_narration"],
            "k": 1,
            "exclude_plan_ids": [plans[0]["id"]],
        },
    )
    _wait_terminal(harness, str(reroll["job_id"]))
    selection_prompts = [user for system, user in calls if "选题操盘手" in system]
    assert len(selection_prompts) == 1
    assert f"不得重复的角度：{plans[0]['angle']}" in selection_prompts[0]
    assert reroll["batch_id"] != first["batch_id"], "重掷是新 batch"
    assert len(plans_repo.list_by_project(memory_db, project_id)) == 2, (
        "方案行只追加、永不覆写：export_jobs.narration_plan_id 必须始终指向当初渲染的那一行"
    )


def test_k_defaults_to_the_settings_value(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    """不传 k 时读 narration.variants_per_mode；RPC 回显实际用的 K，界面才不必自己猜。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings["narration.variants_per_mode"] = "2"
    result = harness.rpc(
        "narration.plan_variants", {"project_id": project_id, "modes": ["raw_clip"]}
    )
    _wait_terminal(harness, str(result["job_id"]))
    assert result["k"] == 2


def test_project_override_beats_the_global_default(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    """projects.settings 的第一个消费端（docs/service/01 §6 的已知限制在此关掉）。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings["narration.variants_per_mode"] = "3"
    harness.rpc(
        "project.update_settings",
        {"project_id": project_id, "settings": {"narration.variants_per_mode": 1}},
    )
    result = harness.rpc(
        "narration.plan_variants", {"project_id": project_id, "modes": ["raw_clip"]}
    )
    _wait_terminal(harness, str(result["job_id"]))
    assert result["k"] == 1, "项目级覆盖没生效，或 JSON 里的 int 没被转成 str"


@pytest.mark.parametrize("k", [0, -1, 9])
def test_k_out_of_range_is_rejected_at_the_rpc_boundary(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path, k: int
) -> None:
    """K 越界必须在派发作业之前拦下：进了作业就只是一条 failed 行，界面拿不到错误码。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    response = harness.router.dispatch(
        RpcRequest(
            id=1,
            method="narration.plan_variants",
            params={"project_id": project_id, "modes": ["raw_clip"], "k": k},
        )
    )
    assert response.error is not None and response.error.code == -32303, response


def test_unknown_excluded_plan_is_rejected_at_the_rpc_boundary(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    response = harness.router.dispatch(
        RpcRequest(
            id=1,
            method="narration.plan_variants",
            params={
                "project_id": project_id,
                "modes": ["raw_clip"],
                "k": 1,
                "exclude_plan_ids": ["不存在的方案"],
            },
        )
    )
    assert response.error is not None and response.error.code == -32304, response


def test_empty_modes_is_rejected(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    response = harness.router.dispatch(
        RpcRequest(
            id=1,
            method="narration.plan_variants",
            params={"project_id": project_id, "modes": []},
        )
    )
    assert response.error is not None and response.error.code == -32302, response


def test_plan_variants_cancel_releases_the_event(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """作业被取消：cancel_events 必须释放，且已产出的方案行留着（规划成果不因取消而回滚）。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    real_voice = narration_api._voice

    def voice_then_cancel(context: Any, plan: Any, settings: Any) -> Any:
        """配完第一条就取消：`_voice` 三个入参（Task 5 重写后无 job_id/mode/index）。"""
        voiced = real_voice(context, plan, settings)
        for event in context.cancel_events.values():
            event.set()
        return voiced

    monkeypatch.setattr(narration_api, "_voice", voice_then_cancel)
    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 3},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "cancelled", status
    assert str(result["job_id"]) not in harness.context.cancel_events, "cancel_events 未释放"

def test_get_plan_returns_row_and_cost(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模式选 intro：3 段 1 槽，段数与槽位数不等，tts_calls 的字面断言才有鉴别力。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["intro_narration"], "k": 1},
    )
    _wait_terminal(harness, str(result["job_id"]))
    plan_id = str(plans_repo.list_by_batch(memory_db, project_id, result["batch_id"])[0]["id"])

    detail = harness.rpc("narration.get_plan", {"plan_id": plan_id})
    assert detail["plan"]["id"] == plan_id
    assert detail["plan"]["angle"] == "角度1"
    plan = PlanData.model_validate(detail["plan"]["plan_data"])
    assert len(plan.timeline) == 6 and len(plan.narration_texts) == 1
    assert detail["cost"] == {"copy_llm_calls": 1, "tts_calls": 1}


def test_get_plan_of_a_silent_mode_costs_no_llm_call(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    """raw_clip 无旁白槽位：成稿 0 次，成本卡不得虚报。"""
    project_id = _seed_project_with_analysis(memory_db, tmp_path, sample_video)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    row = plans_repo.create(
        memory_db, project_id, "raw_clip", ["ep1"],
        PlanData(mode="raw_clip", timeline=[]).model_dump(),
    )
    detail = harness.rpc("narration.get_plan", {"plan_id": str(row["id"])})
    assert detail["cost"] == {"copy_llm_calls": 0, "tts_calls": 0}


def test_get_plan_exposes_the_episodes_a_plan_spans(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """episode_ids 与时间轴逐字相等；两集方案仍是一次成稿往返。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 1},
    )
    _wait_terminal(harness, str(result["job_id"]))
    plan_id = str(plans_repo.list_by_batch(memory_db, project_id, result["batch_id"])[0]["id"])

    detail = harness.rpc("narration.get_plan", {"plan_id": plan_id})
    plan = PlanData.model_validate(detail["plan"]["plan_data"])
    spans: dict[str, list[tuple[float, float]]] = {}
    for segment in plan.timeline:
        spans.setdefault(segment.episode_id, []).append((segment.start, segment.end))

    assert len(spans) == 2, f"夹具前提塌了：只取到 {sorted(spans)}"
    assert len(plan.narration_texts) == 6
    assert detail["plan"]["episode_ids"] == sorted(spans)
    assert sum(len(v) for v in spans.values()) == len(plan.timeline)
    assert detail["cost"] == {"copy_llm_calls": 1, "tts_calls": 6}


def test_get_plan_unknown_id_raises(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    _seed_project_with_analysis(memory_db, tmp_path, sample_video)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    response = harness.router.dispatch(
        RpcRequest(id=1, method="narration.get_plan", params={"plan_id": "不存在"})
    )
    assert response.error is not None and response.error.code == -32304, response


def test_list_plans_can_filter_by_batch(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """给了 batch_id 只回那一组；不给回项目全部。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    first = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 2},
    )
    _wait_terminal(harness, str(first["job_id"]))
    second = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 2},
    )
    _wait_terminal(harness, str(second["job_id"]))

    assert len(harness.rpc("narration.list_plans", {"project_id": project_id})) == 4
    assert len(
        harness.rpc(
            "narration.list_plans",
            {"project_id": project_id, "batch_id": first["batch_id"]},
        )
    ) == 2

