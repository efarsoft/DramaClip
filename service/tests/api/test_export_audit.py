"""B2 渲染后时长审计（**实测 vs 计划声明**）：超阈值只警告，不改状态、不失败。

诚实失败哲学（调研①JJYB）：成片时长与时间轴声明对不上时，把差值写成明账
（warn 日志含实测/声明/差值），而不是伪造元信息或把导出标失败。
阈值 max(8%, 3s)：渲染层的微变速（dedup speed 0.996~1.004）与切点安全抖动
（jitter ±0.3s、保护区顺延 ≤1s）天然带来数个百分点偏差，阈值必须容得下它们，
只抓「段丢了/拼重了」级别的真偏差。
**别把这条与 encoder 的段和闸混为一谈**：`_audit_film_duration` 量的是"成片 vs
各段实测和"，能分辨缺段、拼重，已按 §3.3.1 改成抛错；本条量的是"成片 vs 计划声明"，
分母里混着 jitter 与保护区外扩这些**合法**余量（`protect_slack`），拦不动，留 warn。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import export as export_api
from dramaclip.api import export_audit
from dramaclip.engines.exporter import encoder
from dramaclip.engines.narration.models import PlanData, TimelineSegment
from dramaclip.infra.ffmpeg import probe as probe_mod
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.notify import Notifier


def _seed(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> tuple[SimpleNamespace, str, dict[str, Any], PlanData]:
    """种项目 + 一集真实文件 + 声明 30s 的 raw_clip 编排；返回上下文/export_id/plan_row/plan。"""
    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    project_id = str(projects_repo.create(memory_db, "审计剧", str(tmp_path))["id"])
    episodes_repo.replace_all(
        memory_db,
        project_id,
        [{"episode_number": 1, "source_path": str(source), "duration": 120.0}],
    )
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    plan_data = PlanData(
        mode="raw_clip",
        timeline=[
            TimelineSegment(episode_id=episode_id, start=0.0, end=10.0, audio="original"),
            TimelineSegment(episode_id=episode_id, start=20.0, end=40.0, audio="original"),
        ],
    )  # 声明总时长 = 10 + 20 = 30s
    plans_repo.create(
        memory_db, project_id, "raw_clip", [episode_id], plan_data.model_dump(), status="ready"
    )
    plan_id = str(plans_repo.list_by_project(memory_db, project_id)[0]["id"])
    plan_row = plans_repo.get(memory_db, plan_id)
    assert plan_row is not None
    export_id = exports_repo.create(memory_db, project_id, plan_id, "raw_clip")

    sent: list[dict[str, Any]] = []
    context = SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "cache",
        settings={"export.encoder": "libx264"},  # 跳过 nvenc 真编码探针
        notifier=Notifier(sent.append),
        sent=sent,
    )
    return context, export_id, plan_row, plan_data


def _render(
    monkeypatch: pytest.MonkeyPatch,
    context: SimpleNamespace,
    export_id: str,
    plan_row: dict[str, Any],
    plan_data: PlanData,
    *,
    actual_duration_s: float | None = None,
    probe_raises: bool = False,
) -> Path:
    """桩掉 ffmpeg 执行链与 probe，走生产入口 render_export。"""
    # Phase B 按 jobs 清单逐段验盘（_concat_manifest），假切割也必须落产物
    def _fake_cut(args: list[str], *_a: Any, **_k: Any) -> None:
        Path(args[-1]).write_bytes(b"seg")

    monkeypatch.setattr(encoder, "_run_cut", _fake_cut)

    def _fake_concat(_files: list[Path], target: Path) -> None:
        Path(target).write_bytes(b"film")

    monkeypatch.setattr(encoder, "_concat", _fake_concat)
    monkeypatch.setattr(encoder.loudness, "normalize_in_place", lambda *_a, **_k: None)
    monkeypatch.setattr(export_api.ffmpeg_cover, "extract_cover", lambda *_a, **_k: False)

    def _fake_probe(_path: Path) -> probe_mod.MediaInfo:
        if probe_raises:
            raise ValueError("ffprobe 挂了")
        assert actual_duration_s is not None
        return probe_mod.MediaInfo(
            duration_s=actual_duration_s, width=1080, height=1920, fps=30.0, has_audio=True
        )

    monkeypatch.setattr(export_api.probe, "probe", _fake_probe)
    return export_api.render_export(
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


def _warns(context: SimpleNamespace) -> list[str]:
    return [
        str(m["params"]["message"])
        for m in context.sent
        if m["method"] == "log.append" and m["params"]["level"] == "warn"
    ]


def test_duration_mismatch_warns_with_numbers_but_export_stays_completed(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """实测 60s vs 声明 30s（差一倍，远超阈值）：warn 明账，导出记录仍 completed。"""
    context, export_id, plan_row, plan_data = _seed(memory_db, tmp_path)
    _render(monkeypatch, context, export_id, plan_row, plan_data, actual_duration_s=60.0)

    row = exports_repo.get(memory_db, export_id)
    assert row is not None and row["status"] == exports_repo.STATUS_COMPLETED, "审计不许改状态"
    assert row["duration_s"] == pytest.approx(60.0), "元信息回填的是实测值，不是声明值"
    warns = _warns(context)
    assert len(warns) == 1, f"超阈值必须恰好一条 warn：{warns}"
    message = warns[0]
    assert "60.0" in message and "30.0" in message, f"warn 必须带实测与声明：{message}"
    assert "30.0" in message and ("+" in message or "差" in message), f"warn 必须带差值：{message}"


def test_duration_within_threshold_stays_silent(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """声明 30s、实测 31.5s（+5%，在 max(8%, 3s) 之内）：变速/抖动是已知行为，不吵。"""
    context, export_id, plan_row, plan_data = _seed(memory_db, tmp_path)
    _render(monkeypatch, context, export_id, plan_row, plan_data, actual_duration_s=31.5)
    assert _warns(context) == []
    row = exports_repo.get(memory_db, export_id)
    assert row is not None and row["status"] == exports_repo.STATUS_COMPLETED


def test_short_film_absolute_floor_3s(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """阈值取 max(8%, 3s)：声明 30s 实测 27.5s（-8.3% 但只差 2.5s < 3s）不警告。"""
    context, export_id, plan_row, plan_data = _seed(memory_db, tmp_path)
    _render(monkeypatch, context, export_id, plan_row, plan_data, actual_duration_s=27.5)
    assert _warns(context) == [], "绝对差 2.5s 在 3s 地板之内，不该警告"


def test_audit_probe_failure_never_blocks_export(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """审计自身异常（probe 挂了）静默吞掉：导出照常 completed，不抛、不写 error。"""
    context, export_id, plan_row, plan_data = _seed(memory_db, tmp_path)
    out = _render(monkeypatch, context, export_id, plan_row, plan_data, probe_raises=True)
    assert out.is_file()
    row = exports_repo.get(memory_db, export_id)
    assert row is not None and row["status"] == exports_repo.STATUS_COMPLETED
    assert row["error"] is None


# ---- 成片静默体检（开场 3 秒 / 结尾 3 秒 / 中段死气段）--------------------


def test_silent_windows_parses_unclosed_tail() -> None:
    """ffmpeg 对「静到片尾」的区间只报 start：解析端用时长补，否则结尾判定看不见片尾静默。"""
    stderr = (
        "[s] silence_start: 0.0\n"
        "[s] silence_end: 2.9 | silence_duration: 2.9\n"
        "[s] silence_start: 10.0\n"
        "[s] silence_end: 16.0 | silence_duration: 6.0\n"
        "[s] silence_start: 57.0\n"
    )
    assert export_audit._silent_windows(stderr, 60.0) == [(0.0, 2.9), (10.0, 16.0), (57.0, 60.0)]


def test_silence_quality_flags_opening_tail_and_dead_gaps() -> None:
    """开场无声 + 中段死气 + 无声结尾 → 三条独立账；够不着门槛的短静默零账。"""
    flagged: list[dict[str, Any]] = []
    export_audit._report_silence_quality(
        SimpleNamespace(notifier=Notifier(flagged.append)),
        [(0.0, 2.9), (10.0, 16.0), (57.0, 60.0)],
        60.0,
    )
    messages = [str(m["params"]["message"]) for m in flagged if m["method"] == "log.append"]
    assert any("开场 3 秒质检" in m for m in messages), messages
    assert any("中段死气段检测" in m for m in messages), messages
    assert any("结尾 3 秒质检" in m for m in messages), messages

    quiet: list[dict[str, Any]] = []
    export_audit._report_silence_quality(
        SimpleNamespace(notifier=Notifier(quiet.append)), [(30.0, 33.0)], 60.0
    )
    assert quiet == [], "3s 静默够不着死气门槛（≥5s），不该吵"


def test_silence_quality_skips_no_tts_and_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """零文案模式跳过探测；探测自身挂掉不抛（事后体检不许拖垮已成功的导出）。"""
    calls: list[str] = []
    monkeypatch.setattr(
        export_audit, "_run_silencedetect", lambda path: calls.append(path) or ""
    )
    export_audit._probe_silence_quality(None, "x.mp4", "raw_clip")
    assert calls == [], "零文案模式不该触发探测"

    def _fake_probe(_path: str) -> probe_mod.MediaInfo:
        return probe_mod.MediaInfo(
            duration_s=60.0, width=1080, height=1920, fps=30.0, has_audio=True
        )

    def _boom(_path: str) -> str:
        raise RuntimeError("ffmpeg 炸了")

    monkeypatch.setattr(probe_mod, "probe", _fake_probe)
    monkeypatch.setattr(export_audit, "_run_silencedetect", _boom)
    export_audit._probe_silence_quality(
        SimpleNamespace(notifier=Notifier([])), "x.mp4", "full_narration"
    )


# ---- TTS 回环校验（开关默认关）--------------------------------------------


def _tts_plan(audio: Path) -> Any:
    from dramaclip.engines.narration.models import NarrationText, PlanData

    return PlanData(mode="full_narration", narration_texts=[
        NarrationText(id="n1", text="她攥紧了指节，把肉端上桌", audio_path=str(audio)),
    ])


def _tts_context(tmp_path: Path, settings: dict[str, Any], engine_name: str, heard: str) -> Any:
    from types import SimpleNamespace

    class _FakeEngine:
        name = engine_name

        @staticmethod
        def compute():
            return None

        @staticmethod
        def transcribe(path: Path, language: str = "zh", *, hotwords: str = ""):
            from dramaclip.engines.analysis.models import AsrSegment

            return [AsrSegment(start=0.0, end=1.0, text=heard)]

    audio = tmp_path / "n1.wav"
    audio.write_bytes(b"fake")
    return SimpleNamespace(
        settings={"export.tts_verify": "1", **settings},
        analysis_runtime=SimpleNamespace(transcriber=lambda: _FakeEngine()),
    ), audio


def test_tts_verify_skipped_by_default(tmp_path: Path) -> None:
    """开关默认关：零动作零加载（模型懒加载的硬保证）。"""
    context, audio = _tts_context(
        tmp_path, {"export.tts_verify": "0"}, "paraformer", "完全无关的文本"
    )
    calls: list[object] = []
    context.analysis_runtime.transcriber = (
        lambda: calls.append(1) or context.analysis_runtime.transcriber()
    )
    export_audit._verify_tts_by_asr(context, _tts_plan(audio))
    assert calls == [], "开关关时不得触碰引擎"


def test_tts_verify_flags_high_cer_slot(tmp_path: Path) -> None:
    """字错率超阈值：槽位点名进降级账（留痕不拦片）。"""
    from dramaclip.engines.narration.models import NarrationText, PlanData

    context, audio = _tts_context(tmp_path, {}, "paraformer", "完全无关的不同文本呀")
    plan = PlanData(mode="full_narration", narration_texts=[
        NarrationText(id="n1", text="她攥紧了指节把肉端上桌", audio_path=str(audio)),
    ])
    sent: list[dict[str, Any]] = []
    context.notifier = Notifier(sent.append)
    export_audit._verify_tts_by_asr(context, plan)
    assert any("字错率" in str(m["params"]["message"]) for m in sent if m["method"] == "log.append")


def test_tts_verify_skips_cloud_engine(tmp_path: Path) -> None:
    """云端 ASR 自动跳过：回环是高频质检，不能偷偷计费。"""
    context, audio = _tts_context(tmp_path, {}, "dashscope_cloud:qwen-audio", "任意")
    sent: list[dict[str, Any]] = []
    context.notifier = Notifier(sent.append)
    export_audit._verify_tts_by_asr(context, _tts_plan(audio))
    assert any("云端" in str(m["params"]["message"]) for m in sent if m["method"] == "log.append")


def test_char_error_rate_strips_punctuation() -> None:
    """CER 只比字：标点/空白不进分母，单字错读（7%）必超 5% 阈值。"""
    cer, _ = export_audit._char_error_rate(
        "她攥紧了指节，把肉端上桌。", "她攒紧了指节，把肉端上桌。"
    )
    assert cer == pytest.approx(1 / 11), "剥标点后 11 字 1 错"
