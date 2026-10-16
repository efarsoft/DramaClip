"""P1-3 降级留痕：增强项与事后体检失败绝不挡导出，但必须写明丢了什么。

判据是 §3.3.1 的「允许，但必须留痕」与「测不出 ≠ 合格」。这些分支原先一律写成
`contextlib.suppress(Exception)` 或 `except: pass`——账面干净得像一切正常，而用户
看到灰徽章、没字层的封面、缺实测时长的库里那一行时，分不清"没做成"和"做出来没问题"。
每条断言的都是同一件事：**异常被吃掉的同时，通知面上必须多一条点名的 warn**，
且导出终态不许因为留痕本身再坏一次。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import export as export_api
from dramaclip.api import export_covers as export_covers
from dramaclip.api import narration as narration_api
from dramaclip.engines.exporter import encoder
from dramaclip.engines.narration.models import PlanData, TimelineSegment
from dramaclip.infra.ffmpeg import probe as probe_mod
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.notify import Notifier


def _context(memory_db: sqlite3.Connection, tmp_path: Path) -> SimpleNamespace:
    sent: list[dict[str, Any]] = []
    return SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "cache",
        settings={"export.encoder": "libx264"},
        notifier=Notifier(sent.append),
        sent=sent,
    )


def _warns(context: SimpleNamespace) -> list[str]:
    return [
        str(m["params"]["message"])
        for m in context.sent
        if m["method"] == "log.append" and m["params"]["level"] == "warn"
    ]


def _plan(episode_id: str = "ep1", segments: int = 2) -> PlanData:
    return PlanData(
        mode="raw_clip",
        timeline=[
            TimelineSegment(
                episode_id=episode_id, start=float(i * 10), end=float(i * 10 + 10),
                audio="original",
            )
            for i in range(segments)
        ],
    )


# ── 事后体检：算不出来也要把"这条没核过"写出来 ──────────────────────────


def test_duration_audit_measurement_failure_still_leaves_a_trace(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """审计自身抛错（时间轴形状坏了）：以前整段包在 suppress 里，连 warn 一起吞。

    现在测量失败与超阈值走同一条出口——都点名「成片时长审计未落地」，导出照常成功。
    """
    context = _context(memory_db, tmp_path)
    broken = SimpleNamespace(timeline=None)  # 生产里对应"方案数据坏到 sum() 直接抛"

    export_api._audit_duration(context, broken, 30.0)  # type: ignore[arg-type]

    warns = _warns(context)
    assert len(warns) == 1, f"测量失败必须留一条痕，不是安静地当合格：{warns}"
    assert "成片时长审计" in warns[0] and "TypeError" in warns[0], warns[0]


def test_clock_audit_failure_leaves_a_trace(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """台词时钟对账抛错：丢的是这条片子唯一的驻留窗重叠账面，静默等于假通过。"""
    context = _context(memory_db, tmp_path)

    export_api._log_clock_audit(context, [(1, "两行", 0), (2, 1, 0)])  # type: ignore[list-item]

    warns = _warns(context)
    assert len(warns) == 1, f"对账算不出来必须留痕（原先suppress把日志那句也吞了）：{warns}"
    assert "台词时钟对账" in warns[0], warns[0]


def test_render_meta_and_selfcheck_failures_trace_but_export_stays_completed(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """渲染尾部三段增强（元信息/自检/封面）各自抛错：三条痕都要在，终态仍是 completed。

    这是 `pass` / `suppress(Exception)` 最密集的一段。改成留痕之后最怕的是"顺手把
    不挡导出变成挡导出"，所以这里连终态一起钉死。
    """
    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    project_id = str(projects_repo.create(memory_db, "留痕剧", str(tmp_path))["id"])
    episodes_repo.replace_all(
        memory_db, project_id,
        [{"episode_number": 1, "source_path": str(source), "duration": 120.0}],
    )
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    plan_data = _plan(episode_id)
    plans_repo.create(
        memory_db, project_id, "raw_clip", [episode_id], plan_data.model_dump(), status="ready"
    )
    plan_id = str(plans_repo.list_by_project(memory_db, project_id)[0]["id"])
    plan_row = plans_repo.get(memory_db, plan_id)
    assert plan_row is not None
    export_id = exports_repo.create(memory_db, project_id, plan_id, "raw_clip")
    context = _context(memory_db, tmp_path)

    def _fake_cut(args: list[str], *_a: Any, **_k: Any) -> None:
        # Phase B 按 jobs 清单逐段验盘（_concat_manifest），假切割也必须落产物
        Path(args[-1]).write_bytes(b"seg")

    monkeypatch.setattr(encoder, "_run_cut", _fake_cut)
    monkeypatch.setattr(encoder, "_concat", lambda _f, target: Path(target).write_bytes(b"film"))
    monkeypatch.setattr(encoder.loudness, "normalize_in_place", lambda *_a, **_k: None)
    monkeypatch.setattr(export_api, "_selfcheck_one", lambda *_a, **_k: (_ for _ in ()).throw(
        RuntimeError("自检探针炸了")
    ))

    def _probe_boom(_path: Path) -> probe_mod.MediaInfo:
        raise ValueError("ffprobe 挂了")

    def _boom_cover(*_a: Any, **_k: Any) -> None:
        raise OSError("封面截帧起不来")

    monkeypatch.setattr(export_api.probe, "probe", _probe_boom)
    monkeypatch.setattr(export_api, "_extract_cover", _boom_cover)
    out = export_api.render_export(
        context,  # type: ignore[arg-type]
        export_api.ExportRun(
            export_id=export_id,
            project_id=str(plan_row["project_id"]),
            plan_row=plan_row,
            plan_data=plan_data,
            cancel_event=threading.Event(),
        ),
        report=lambda _p, _m: None,
    )

    assert out.is_file()
    row = exports_repo.get(memory_db, export_id)
    assert row is not None and row["status"] == exports_repo.STATUS_COMPLETED, "留痕不许改终态"
    warns = _warns(context)
    joined = "\n".join(warns)
    for subject in ("成片元信息回填与时长审计", "导出期四项自检", "封面截帧"):
        assert subject in joined, f"增强项断供少了点名的痕：{subject}\n{joined}"


def test_titles_generation_failure_traces_and_export_is_not_blocked(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """`_ensure_titles` 原先整个包在 `contextlib.suppress(Exception)` 里：LLM 断了、
    封面没字层、列表没候选可选，账面却一片干净。
    """
    context = _context(memory_db, tmp_path)
    monkeypatch.setattr(
        narration_api, "generate_titles",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("LLM 未配置")),
    )

    export_api._ensure_titles(  # type: ignore[arg-type]
        context, {"id": "plan-1", "titles": []}
    )

    warns = _warns(context)
    assert len(warns) == 1 and "候选标题生成" in warns[0], warns


# ── 回读与封面链：降级方向不变，但要说清丢了哪一层 ──────────────────────


def test_plan_readback_corruption_traces_instead_of_silently_graying_selfcheck(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """方案回读坏数据：返回 None 是对的（追溯断链不猜），但自检基准没了必须记账。"""
    context = _context(memory_db, tmp_path)
    monkeypatch.setattr(
        export_api.plans_repo, "get", lambda _conn, _pid: {"plan_data": "{不是 JSON"}
    )

    assert export_api._load_plan_data(context, "plan-1") is None
    warns = _warns(context)
    assert len(warns) == 1 and "编排方案回读" in warns[0], warns


def test_cover_title_failure_falls_back_to_plain_cover_with_trace(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """取封面字层标题时读库抛错：退回无字层可以，悄悄退回不行。"""
    broken_conn = None  # plans_repo.get(None, …) 当场抛
    context = _context(memory_db, tmp_path)
    context.conn = broken_conn

    assert export_api._cover_title(context, {"id": "plan-1", "titles": []}) is None
    warns = _warns(context)
    assert len(warns) == 1 and "封面字层标题" in warns[0], warns


def test_cover_source_frame_failure_records_the_subtitle_burn_fallback(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """源截帧抛错 → 封面改从成片截（画面带烧录字幕）：这层降级必须留痕。"""
    context = _context(memory_db, tmp_path)
    seen: list[str] = []

    def _boom(*_a: Any, **_k: Any) -> None:
        raise ValueError("源输入形状不对")

    monkeypatch.setattr(export_covers, "_cover_source_frame", _boom)
    monkeypatch.setattr(
        export_api.ffmpeg_cover,
        "extract_cover",
        lambda path, *_a, **_k: seen.append(Path(path).name) or True,
    )

    export_api._extract_cover(
        context, "exp1", tmp_path / "film.mp4",
        plan_data=_plan(), episode_paths={"ep1": str(tmp_path / "ep1.mp4")},
        out_size=(1080, 1920),
    )

    warns = _warns(context)
    assert len(warns) == 1 and "源素材截帧" in warns[0], warns
    assert seen == ["film.mp4"], f"回退仍要从成片截，留下封面可用性：{seen}"


def test_degradation_note_survives_a_dead_notification_channel(
    memory_db: sqlite3.Connection, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """留痕自己不许再被吞：通知面投递失败时兜到进程日志，且绝不把导出拖成失败。

    这条钉的是本次改动**新引入**的风险（不是修前的旧行为——修前整段包在 suppress
    里，投递失败同样炸不出来）：体检文案算完后在 guard 外发，管道一旦断了就是
    一条能把已成功导出拖成失败的异常。`_emit_note` 把它兜住。
    """
    context = _context(memory_db, tmp_path)

    class _Dead:
        def log(self, *_a: Any, **_k: Any) -> None:
            raise OSError("管道已关闭")

    context.notifier = _Dead()
    with caplog.at_level("WARNING", logger="dramaclip.api.export_audit"):
        export_api._note_degraded(context, "台词时钟对账", "本条成片没有账面", ValueError("x"))
    assert "台词时钟对账" in caplog.text, "通知面死了也不能把留痕一起带走"

    caplog.clear()
    with caplog.at_level("INFO", logger="dramaclip.api.export_audit"):
        export_api._log_clock_audit(context, [(3, 2, 1)])  # 正常算得出，只是投不出去
    assert "台词时钟对账：烧录台词 3 行" in caplog.text, "正常账面也走同一条兜底"


# ── 拼片几何签名：量不到就走保守路径，但保守路径是花钱的那条 ────────────


def _assert_signature_traces(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    run: Any,
) -> None:
    monkeypatch.setattr(encoder.subprocess, "run", run)
    with caplog.at_level("WARNING", logger="dramaclip.engines.exporter.encoder"):
        assert encoder._video_signature(Path("seg_000.mp4")) is None
    assert "全量重编码" in caplog.text, caplog.text


def test_signature_probe_exception_warns_about_full_reencode(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`_video_signature` 探测抛错 → None → Phase B 全量重编码。

    返回 None 是对的（宁可重编码也不把几何不齐的段流复制），但"这次没走上流复制"
    得能从日志里查出来——它直接解释耗时为什么翻倍。
    """

    def _boom(*_a: Any, **_k: Any) -> None:
        raise OSError("ffprobe 起不来")

    _assert_signature_traces(monkeypatch, caplog, _boom)


def test_signature_probe_nonzero_exit_warns_about_full_reencode(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """ffprobe 正常起来但报错退出（损坏段/无权限）：同样一条保守路径，同样要留痕。"""

    def _failed(*_a: Any, **_k: Any) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stdout="", stderr="Invalid data found")

    _assert_signature_traces(monkeypatch, caplog, _failed)
