"""批次二·原声段 ASR 台词字幕：词级窗口裁剪 + 相对时间轴烧录（接线方案 B）。

crop_dialogue_lines 是纯函数（单元钉裁剪/归属/降级规则）；
render_export 集成钉「ass 文件真的写出来、时间轴相对段起点、旧库不 raise」。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import export as export_api
from dramaclip.engines.exporter import encoder
from dramaclip.engines.narration.models import PlanData, TimelineSegment
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.notify import Notifier

# --- crop_dialogue_lines 纯函数规则 -------------------------------------------


def _word(start: float, end: float, text: str) -> dict[str, Any]:
    return {"start": start, "end": end, "word": text, "probability": 1.0}


def test_crop_keeps_only_words_inside_the_window_and_rebases() -> None:
    """句子跨段边界：只留窗口内的词，文本=留词拼接，时间重定基到段内相对秒。"""
    items = [
        {
            "start": 18.0,
            "end": 24.0,
            "text": "前面的话边界词今天天气不错",
            "words": [
                _word(18.0, 19.8, "前面的话"),  # 完全在窗口外 → 丢
                _word(19.8, 20.2, "边界词"),    # 跨界：重叠 0.2 / 长 0.4 = 恰好一半 → 留
                _word(20.2, 21.4, "今天天气"),  # 完全在窗口内 → 留
                _word(21.4, 23.0, "不错"),      # 跨界：重叠 0.6 / 长 1.6 < 一半 → 丢
            ],
        }
    ]
    cropped = export_api.crop_dialogue_lines(items, 20.0, 22.0)
    assert len(cropped) == 1
    line = cropped[0]
    assert line["text"] == "边界词今天天气"
    # 重定基：窗口 20.0 起点 → 段内相对秒
    assert line["start"] == pytest.approx(0.0)
    assert line["end"] == pytest.approx(1.4)
    # 跨界词钳到窗口起点，随后词顺次重定基
    assert [w["start"] for w in line["words"]] == pytest.approx([0.0, 0.2])
    assert [w["end"] for w in line["words"]] == pytest.approx([0.2, 1.4])


def test_crop_boundary_word_needs_majority_overlap() -> None:
    """跨界词按重叠过半归属：重叠 < 词长一半丢，≥ 一半留（FunClip 多数重叠思路）。"""
    items = [
        {
            "start": 0.0,
            "end": 10.0,
            "text": "甲乙",
            "words": [_word(9.0, 11.0, "甲"), _word(11.0, 13.0, "乙")],
        }
    ]
    # 窗口到 10.2：甲重叠 1.0/2.0 = 一半 → 留；窗口到 9.9：甲重叠 0.9/2.0 < 一半 → 丢
    kept = export_api.crop_dialogue_lines(items, 0.0, 10.2)
    assert kept and kept[0]["text"] == "甲"
    dropped = export_api.crop_dialogue_lines(items, 0.0, 9.9)
    assert dropped == []


def test_crop_drops_sentences_outside_the_window() -> None:
    items = [
        {"start": 0.0, "end": 5.0, "text": "早于窗口", "words": [_word(0.0, 5.0, "早于窗口")]},
        {"start": 40.0, "end": 45.0, "text": "晚于窗口", "words": [_word(40.0, 45.0, "晚于窗口")]},
    ]
    assert export_api.crop_dialogue_lines(items, 20.0, 30.0) == []


def test_crop_without_words_degrades_to_whole_sentence_clamped() -> None:
    """旧库（words 空列表）：句级降级——整句与窗口有交集就显示整句，钳到窗口，不 raise。"""
    items = [{"start": 22.0, "end": 26.0, "text": "整句台词", "words": []}]
    cropped = export_api.crop_dialogue_lines(items, 20.0, 25.0)
    assert len(cropped) == 1
    assert cropped[0]["text"] == "整句台词"
    assert cropped[0]["words"] is None
    assert cropped[0]["start"] == pytest.approx(2.0)
    assert cropped[0]["end"] == pytest.approx(5.0)  # 钳到窗口终点 25.0 → 相对 5.0


def test_crop_survives_garbage_items() -> None:
    """坏行（缺字段/坏类型/end<=start）逐个跳过，不炸整段渲染。"""
    items: list[dict[str, Any]] = [
        {"start": 1.0, "end": 1.0, "text": "零长"},
        {"start": "x", "end": 2.0, "text": "坏类型"},
        {"text": "没时间戳"},
        {"start": 2.0, "end": 3.0, "text": "好句", "words": "不是列表"},
    ]
    cropped = export_api.crop_dialogue_lines(items, 0.0, 10.0)
    assert [item["text"] for item in cropped] == ["好句"]


# --- render_export 集成 --------------------------------------------------------


def _seed(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    asr_items: list[dict[str, Any]] | None,
    *,
    seg_start: float = 20.0,
    seg_end: float = 30.0,
    mode: str = "intro_narration",
) -> tuple[SimpleNamespace, str, dict[str, Any], PlanData]:
    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    project_id = str(projects_repo.create(memory_db, "台词剧", str(tmp_path))["id"])
    episodes_repo.replace_all(
        memory_db,
        project_id,
        [{"episode_number": 1, "source_path": str(source), "duration": 120.0}],
    )
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    if asr_items is not None:
        analysis_repo.upsert(
            memory_db,
            episode_id,
            asr_segments=json.dumps(asr_items),
            scene_data=None,
            audio_features=None,
        )
    plan_data = PlanData(
        mode=mode,
        timeline=[
            TimelineSegment(
                episode_id=episode_id, start=seg_start, end=seg_end, audio="original"
            )
        ],
    )
    plans_repo.create(
        memory_db, project_id, mode, [episode_id], plan_data.model_dump(), status="ready"
    )
    plan_id = str(plans_repo.list_by_project(memory_db, project_id)[0]["id"])
    plan_row = plans_repo.get(memory_db, plan_id)
    assert plan_row is not None
    export_id = exports_repo.create(memory_db, project_id, plan_id, mode)
    context = SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "cache",
        settings={"export.encoder": "libx264"},
        notifier=Notifier(lambda _m: None),
    )
    return context, export_id, plan_row, plan_data


def _render(
    monkeypatch: pytest.MonkeyPatch,
    context: SimpleNamespace,
    export_id: str,
    plan_row: dict[str, Any],
    plan_data: PlanData,
) -> list[list[str]]:
    """桩掉 ffmpeg/抖动/probe，走生产 render_export，返回每段切割命令。"""
    monkeypatch.setattr(encoder.jitter, "safe_times", lambda s, e, _z, **_k: (s, e))
    calls: list[list[str]] = []
    monkeypatch.setattr(encoder, "_run_cut", lambda args, *_a, **_k: calls.append(args))
    monkeypatch.setattr(
        encoder, "_concat", lambda _files, target: Path(target).write_bytes(b"film")
    )
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


def test_render_burns_asr_dialogue_with_relative_timeline(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """原声段拿到 ASR 台词字幕；ass 时间轴相对段起点（22s 的句子 → 2.00）。"""
    items = [
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
    context, export_id, plan_row, plan_data = _seed(memory_db, tmp_path, items)
    calls = _render(monkeypatch, context, export_id, plan_row, plan_data)
    joined = " ".join(calls[0])
    assert "ass=" in joined, f"原声段切割命令没带字幕滤镜：{joined}"
    ass = _ass_file(context, export_id).read_text(encoding="utf-8")
    assert "Dialogue: 0,0:00:02.00,0:00:04.00" in ass, f"时间轴不是段内相对：{ass}"
    assert "今天天气不错" in ass


def test_render_skips_dialogue_when_window_is_silent(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """段窗口内没有句子：不写字幕文件，切割命令不带 ass 滤镜。"""
    items = [{"start": 0.0, "end": 5.0, "text": "窗口外", "words": [_word(0.0, 5.0, "窗口外")]}]
    context, export_id, plan_row, plan_data = _seed(memory_db, tmp_path, items)
    calls = _render(monkeypatch, context, export_id, plan_row, plan_data)
    assert "ass=" not in " ".join(calls[0])
    assert not _ass_file(context, export_id).exists()


def test_render_degrades_to_sentence_level_without_words(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """旧库 words=[]：整句显示（钳到窗口），时长按句级区间。"""
    items = [{"start": 22.0, "end": 34.0, "text": "整句台词钳到窗口", "words": []}]
    context, export_id, plan_row, plan_data = _seed(memory_db, tmp_path, items)
    _render(monkeypatch, context, export_id, plan_row, plan_data)
    ass = _ass_file(context, export_id).read_text(encoding="utf-8")
    # 窗口 20-30：句子钳到 22→30，相对 2.00→10.00
    assert "Dialogue: 0,0:00:02.00,0:00:10.00" in ass, ass
    assert "整句台词钳到窗口" in ass


@pytest.mark.parametrize("asr_items", [None, []])
def test_render_survives_missing_or_empty_asr(
    monkeypatch: pytest.MonkeyPatch,
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    asr_items: list[dict[str, Any]] | None,
) -> None:
    """无分析记录 / 空 asr_segments：不 raise，原声段照旧无字幕。"""
    context, export_id, plan_row, plan_data = _seed(memory_db, tmp_path, asr_items)
    calls = _render(monkeypatch, context, export_id, plan_row, plan_data)
    assert "ass=" not in " ".join(calls[0])
    row = exports_repo.get(memory_db, export_id)
    assert row is not None and row["status"] == exports_repo.STATUS_COMPLETED


def test_raw_clip_mode_gets_no_dialogue_subtitles(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """raw_clip 整片不烧字幕（与既有 subtitle_burner 的门槛一致）。"""
    items = [
        {
            "start": 22.0,
            "end": 24.0,
            "text": "今天天气不错",
            "words": [_word(22.0, 24.0, "今天天气不错")],
        }
    ]
    context, export_id, plan_row, plan_data = _seed(
        memory_db, tmp_path, items, mode="raw_clip"
    )
    calls = _render(monkeypatch, context, export_id, plan_row, plan_data)
    assert "ass=" not in " ".join(calls[0])
