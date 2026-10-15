"""转写精炼的**回写与取数口径**：精炼段必须落库，语义层吃的那份必须与库里同一份。

`upsert` 先写融合分段，之后 `refine_segments` 成功只改内存变量——不补写就等于
narration/auto_voice 全线读到精炼前文本（本层白跑）；而语义层 `enhance(raw)` 拿到的
`raw` 是融合前的原生分段，重入路径 `_resumable_raw` 又从库里重建（融合后）——同一集
会因「上轮有没有死在语义层」跑出不同的高光/冲突打分，违「同一含义不得第二处真相源」。

直连 `_analyze_one`（不起作业线程池）：本文件只验落库与取数口径，绕开
test_analysis.py 里那两条已知受套件时序污染的 job-wait 用例。
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import analysis as analysis_api
from dramaclip.engines.analysis import llm_refine
from dramaclip.engines.analysis.models import AsrSegment, AudioFeatures, EpisodeRawAnalysis
from dramaclip.infra import jobs
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.notify import Notifier

#: 三份文本各自代表链路上的一层，互不相同才能看出谁吃到了谁
PRE_FUSION = "融合前的整段台词"
FUSED = "融合后的分行台词"
REFINED = "精炼后的断句台词"


def _seg(text: str) -> AsrSegment:
    return AsrSegment(start=0.0, end=1.0, text=text)


@pytest.fixture
def env(
    memory_db: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> SimpleNamespace:
    """第一层→融合→精炼→语义的桩链路，只保留真实落库与真实取数。"""
    projects_repo.create(memory_db, "p", str(tmp_path))
    episodes_repo.replace_all(
        memory_db,
        str(memory_db.execute("SELECT id FROM projects").fetchone()[0]),
        [{"episode_number": 1, "source_path": str(tmp_path / "1.mp4"), "duration": 60.0}],
    )
    sent: list[dict[str, Any]] = []
    context = SimpleNamespace(
        conn=memory_db,
        settings={"asr.language": "zh"},
        notifier=Notifier(sent.append),
        job_store=jobs.JobStore(memory_db),
        analysis_runtime=SimpleNamespace(transcriber=lambda: None),
        work_dir=tmp_path / "work",
        data_dir=tmp_path,
        cancel_events={},
    )
    # 转写管线：产出融合前的整段
    monkeypatch.setattr(
        analysis_api.pipeline,
        "analyze_episode",
        lambda **_kw: EpisodeRawAnalysis(
            asr_segments=[_seg(PRE_FUSION)], audio=AudioFeatures()
        ),
    )
    # 融合：返回新列表（真实实现就是不改 raw，语义层的坑正在这）
    monkeypatch.setattr(
        analysis_api, "_fuse_ocr", lambda *_a, **_k: ([_seg(FUSED)], None, None, None)
    )
    monkeypatch.setattr(analysis_api, "_contact_sheet", lambda *_a: None)
    monkeypatch.setattr(analysis_api, "_describe_frames", lambda *_a, **_k: [])
    # 语义层：记录它真正吃到了哪份转写
    seen: dict[str, list[str]] = {}

    def fake_enhance(raw: Any, _settings: Any, **_kw: Any) -> Any:
        seen["asr"] = [str(seg.text) for seg in raw.asr_segments]
        return SimpleNamespace(conflict_scores=[], highlights=[], genre="")

    monkeypatch.setattr(analysis_api.semantic_pipeline, "enhance", fake_enhance)
    episode = episodes_repo.list_by_project(
        memory_db, str(memory_db.execute("SELECT id FROM projects").fetchone()[0])
    )[0]
    return SimpleNamespace(
        context=context,
        conn=memory_db,
        episode=episode,
        sent=sent,
        seen=seen,
        monkeypatch=monkeypatch,
    )


def _run(env: SimpleNamespace) -> bool:
    return analysis_api._analyze_one(  # noqa: SLF001 - 直连内部编排，不起作业线程
        env.context, "job-1", env.episode, 0, 1, "zh", threading.Event()
    )


def _stored(env: SimpleNamespace) -> list[str]:
    record = analysis_repo.get(env.conn, str(env.episode["id"]))
    assert record is not None
    return [str(item["text"]) for item in json.loads(record["asr_segments"] or "[]")]


def test_refined_segments_reach_the_database(env: SimpleNamespace) -> None:
    """精炼生效却不落库 = 下游全线读到精炼前文本；库里必须见 REFINED。"""
    env.monkeypatch.setattr(
        analysis_api.llm_refine,
        "refine_segments",
        lambda *_a, **_k: llm_refine.RefineOutcome(
            segments=[_seg(REFINED)], applied=True, detail="测试"
        ),
    )
    assert _run(env) is True
    assert _stored(env) == [REFINED]
    assert _stored(env) != [FUSED], "库里还是融合分段——精炼产物只活在内存里"


def test_refined_segments_are_what_the_semantic_layer_eats(env: SimpleNamespace) -> None:
    """语义层与库内同一份：吃融合前文本会随「上轮是否死在语义层」给出不同高光。"""
    env.monkeypatch.setattr(
        analysis_api.llm_refine,
        "refine_segments",
        lambda *_a, **_k: llm_refine.RefineOutcome(
            segments=[_seg(REFINED)], applied=True, detail="测试"
        ),
    )
    assert _run(env) is True
    assert env.seen["asr"] == [REFINED]


def test_refine_rejected_still_keeps_one_truth(env: SimpleNamespace) -> None:
    """护栏拒绝→回退融合产物：库里与语义层都得是 FUSED，不许一个是融合前。"""
    env.monkeypatch.setattr(
        analysis_api.llm_refine,
        "refine_segments",
        lambda *_a, **_k: llm_refine.RefineOutcome(
            segments=[_seg(FUSED)], applied=False, detail="对齐护栏拒绝"
        ),
    )
    assert _run(env) is True
    assert _stored(env) == [FUSED]
    assert env.seen["asr"] == [FUSED], "语义层吃到融合前分段：与库里不是同一份文本"
    assert any(
        m["params"].get("level") == "warn" and "精炼未生效" in str(m["params"].get("message"))
        for m in env.sent
        if m["method"] == "log.append"
    ), "精炼未生效必须留痕，不许静默回退"
