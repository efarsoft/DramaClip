"""A2 接线验收：episode_analysis.subtitle_band → 烧录字幕 MarginV 避让（parent 接线）。

数据链三段各有自己的测试（subtitle_ocr 探测 / repo 落库 / ass_generator 换算），
这里钉的是断在中间的**接线**：render_export 预取循环解析 band 并传给两个
build_ass 调用点（旁白 burner 与原声 dialogue_subtitle）。
降级不可见是硬验收：无 band / 坏 JSON 时 ass 与现状逐字节一致。
"""

from __future__ import annotations

import itertools
import json
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import export as export_api
from dramaclip.engines.exporter import encoder
from dramaclip.engines.narration.models import NarrationText, PlanData, TimelineSegment
from dramaclip.engines.subtitle import presets
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.notify import Notifier

_SEED_COUNTER = itertools.count()


def _fresh_root(tmp_path: Path) -> Path:
    """projects.source_path 有 UNIQUE 约束：每次播种用独立根目录。"""
    root = tmp_path / f"seed{next(_SEED_COUNTER)}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _word(start: float, end: float, text: str) -> dict[str, Any]:
    return {"start": start, "end": end, "word": text, "probability": 1.0}


_ITEMS = [
    {
        "start": 22.0,
        "end": 24.0,
        "text": "今天天气不错",
        "words": [
            _word(22.0, 22.5, "今天"),
            _word(22.5, 23.2, "天气"),
            _word(23.2, 24.0, "不错"),
        ],
    }
]


def _seed_original(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> tuple[SimpleNamespace, str, dict[str, Any], PlanData, str]:
    """原声段（audio=original）单段方案；返回 (context, export_id, plan_row, plan, episode_id)。"""
    root = _fresh_root(tmp_path)
    source = root / "ep1.mp4"
    source.write_bytes(b"x")
    project_id = str(projects_repo.create(memory_db, "避让剧", str(root))["id"])
    episodes_repo.replace_all(
        memory_db,
        project_id,
        [{"episode_number": 1, "source_path": str(source), "duration": 120.0}],
    )
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    analysis_repo.upsert(
        memory_db,
        episode_id,
        asr_segments=json.dumps(_ITEMS),
        scene_data=None,
        audio_features=None,
    )
    plan_data = PlanData(
        mode="intro_narration",
        timeline=[
            TimelineSegment(episode_id=episode_id, start=20.0, end=30.0, audio="original")
        ],
    )
    plans_repo.create(
        memory_db,
        project_id,
        "intro_narration",
        [episode_id],
        plan_data.model_dump(),
        status="ready",
    )
    plan_id = str(plans_repo.list_by_project(memory_db, project_id)[0]["id"])
    plan_row = plans_repo.get(memory_db, plan_id)
    assert plan_row is not None
    export_id = exports_repo.create(memory_db, project_id, plan_id, "intro_narration")
    context = SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "cache",
        settings={"export.encoder": "libx264"},
        notifier=Notifier(lambda _m: None),
    )
    return context, export_id, plan_row, plan_data, episode_id


def _seed_narrated(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> tuple[SimpleNamespace, str, dict[str, Any], PlanData, str]:
    """旁白段（audio=narration + narration_texts 带 audio_path）：走 burner 路径。"""
    root = _fresh_root(tmp_path)
    source = root / "ep1.mp4"
    source.write_bytes(b"x")
    audio = root / "tts" / "intro.mp3"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"mp3")
    project_id = str(projects_repo.create(memory_db, "避让剧2", str(root))["id"])
    episodes_repo.replace_all(
        memory_db,
        project_id,
        [{"episode_number": 1, "source_path": str(source), "duration": 120.0}],
    )
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    analysis_repo.upsert(
        memory_db,
        episode_id,
        asr_segments=json.dumps(_ITEMS),
        scene_data=None,
        audio_features=None,
    )
    plan_data = PlanData(
        mode="intro_narration",
        timeline=[
            TimelineSegment(
                episode_id=episode_id,
                start=20.0,
                end=30.0,
                audio="narration",
                narration_id="intro-1",
                subtitle_text="他以为她只是个替身",
            )
        ],
        narration_texts=[
            NarrationText(
                id="intro-1", text="他以为她只是个替身", audio_path=str(audio), duration=4.0
            )
        ],
    )
    plans_repo.create(
        memory_db,
        project_id,
        "intro_narration",
        [episode_id],
        plan_data.model_dump(),
        status="ready",
    )
    plan_id = str(plans_repo.list_by_project(memory_db, project_id)[0]["id"])
    plan_row = plans_repo.get(memory_db, plan_id)
    assert plan_row is not None
    export_id = exports_repo.create(memory_db, project_id, plan_id, "intro_narration")
    context = SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "cache",
        settings={"export.encoder": "libx264"},
        notifier=Notifier(lambda _m: None),
    )
    return context, export_id, plan_row, plan_data, episode_id


def _render(
    monkeypatch: pytest.MonkeyPatch,
    context: SimpleNamespace,
    export_id: str,
    plan_row: dict[str, Any],
    plan_data: PlanData,
) -> list[list[str]]:
    monkeypatch.setattr(encoder.jitter, "safe_times", lambda s, e, _z, **_k: (s, e))
    calls: list[list[str]] = []
    monkeypatch.setattr(encoder, "_run_cut", lambda args, *_a, **_k: calls.append(args))
    monkeypatch.setattr(encoder, "_concat", lambda _f, target: Path(target).write_bytes(b"film"))
    monkeypatch.setattr(encoder.loudness, "normalize_in_place", lambda *_a, **_k: None)
    monkeypatch.setattr(export_api.ffmpeg_cover, "extract_cover", lambda *_a, **_k: False)

    def _boom(_path: Path) -> Any:
        raise ValueError("probe 桩")

    monkeypatch.setattr(export_api.probe, "probe", _boom)
    export_api.render_export(
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
    return calls


def _ass_file(context: SimpleNamespace, export_id: str, index: int = 0) -> Path:
    return Path(context.work_dir) / "export" / export_id / f"seg_{index:03d}.ass"


# ---- 原声段（dialogue_subtitle 回调）------------------------------------------


def test_dialogue_subtitle_lifts_margin_over_source_band(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """band(0.85,0.95) → 带内压位：盒底 = (1-0.95)×1920，盒高按 preset 字号估。"""
    context, export_id, plan_row, plan_data, episode_id = _seed_original(memory_db, tmp_path)
    analysis_repo.update_subtitle_band(memory_db, episode_id, json.dumps([0.85, 0.95]))
    _render(monkeypatch, context, export_id, plan_row, plan_data)
    ass = _ass_file(context, export_id).read_text(encoding="utf-8")
    assert "今天天气不错" in ass
    from dramaclip.engines.subtitle.ass_generator import cover_band_margin_v

    preset = presets.get_preset("conflict-impact")
    font_px = int(preset.get("font", {}).get("size", 64))
    expected = cover_band_margin_v((0.85, 0.95), 90, None, font_px)
    style = next(ln for ln in ass.splitlines() if ln.startswith("Style: DC,"))
    assert style.split(",")[-2].strip() == str(expected)


def test_dialogue_subtitle_without_band_is_byte_identical(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """无 band（NULL）→ ass 与现状逐字节一致（MarginV=预设 90）。"""
    context, export_id, plan_row, plan_data, _ep = _seed_original(memory_db, tmp_path)
    _render(monkeypatch, context, export_id, plan_row, plan_data)
    no_band = _ass_file(context, export_id).read_text(encoding="utf-8")

    context2, export_id2, plan_row2, plan_data2, ep2 = _seed_original(memory_db, tmp_path)
    # 同库同集，band 保持 NULL；再渲一次应逐字节相同（渲染无随机源：无 dedup 抖动影响 ass）
    _render(monkeypatch, context2, export_id2, plan_row2, plan_data2)
    again = _ass_file(context2, export_id2).read_text(encoding="utf-8")
    assert no_band == again
    style = next(ln for ln in no_band.splitlines() if ln.startswith("Style: DC,"))
    assert style.split(",")[-2].strip() == "90"


def test_dialogue_subtitle_survives_garbage_band(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """坏 JSON / 形状不对 → 不炸、当无 band（现状 90）。降级不可见。"""
    for garbage in ('{"top": 0.8}', "[0.85, 'x']", "[0.85]", "not-json", "[true, 0.9]"):
        context, export_id, plan_row, plan_data, episode_id = _seed_original(memory_db, tmp_path)
        analysis_repo.update_subtitle_band(memory_db, episode_id, garbage)
        calls = _render(monkeypatch, context, export_id, plan_row, plan_data)
        assert calls, f"垃圾 band {garbage!r} 让渲染没出段命令"
        ass = _ass_file(context, export_id).read_text(encoding="utf-8")
        style = next(ln for ln in ass.splitlines() if ln.startswith("Style: DC,"))
        assert style.split(",")[-2].strip() == "90", f"垃圾 band {garbage!r} 改了 MarginV"


# ---- 旁白段（burn_subtitle 路径）----------------------------------------------


def test_burn_subtitle_covers_source_band(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """burner 路径带内压位：band(0.80,0.92) → MarginV 按盒底贴带底、盒高按 preset 字号估。"""
    context, export_id, plan_row, plan_data, episode_id = _seed_narrated(memory_db, tmp_path)
    analysis_repo.update_subtitle_band(memory_db, episode_id, json.dumps([0.80, 0.92]))
    _render(monkeypatch, context, export_id, plan_row, plan_data)
    ass = _ass_file(context, export_id).read_text(encoding="utf-8")
    assert "他以为她只是个替身" in ass
    from dramaclip.engines.subtitle.ass_generator import cover_band_margin_v

    preset = presets.get_preset("conflict-impact")
    font_px = int(preset.get("font", {}).get("size", 64))
    expected = cover_band_margin_v((0.80, 0.92), 90, None, font_px)
    style = next(ln for ln in ass.splitlines() if ln.startswith("Style: DC,"))
    assert style.split(",")[-2].strip() == str(expected)


def test_burn_subtitle_non_overlapping_band_keeps_preset(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """band 顶低于我们字幕底边（不重叠）→ 不无谓抬字幕，保持 90。"""
    context, export_id, plan_row, plan_data, episode_id = _seed_narrated(memory_db, tmp_path)
    analysis_repo.update_subtitle_band(memory_db, episode_id, json.dumps([0.98, 1.0]))
    _render(monkeypatch, context, export_id, plan_row, plan_data)
    ass = _ass_file(context, export_id).read_text(encoding="utf-8")
    style = next(ln for ln in ass.splitlines() if ln.startswith("Style: DC,"))
    assert style.split(",")[-2].strip() == "90"
