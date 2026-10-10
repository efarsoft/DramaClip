"""批次二·原声段 ASR 台词字幕：词级窗口裁剪 + 相对时间轴烧录（接线方案 B）。

crop_dialogue_lines 是纯函数（单元钉裁剪/归属/降级规则，和「行窗是唯一显示时钟」这条
立案④归一）；render_export 集成钉「ass 文件真的写出来、时间轴相对段起点、旧库不 raise」，
外加台词时钟对账的出片明账。
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
    """句子跨段边界：只留窗口内的词，文本=留词拼接，时间重定基到段内相对秒。

    行窗 18-24 比词戳跨度 18-23 宽，按立案④词戳仿射贴合行窗（×1.2）后再归属：
    留下的词不变，行内比例不变，绝对时刻换成行窗刻度。
    """
    items = [
        {
            "start": 18.0,
            "end": 24.0,
            "text": "前面的话边界词今天天气不错",
            "words": [
                _word(18.0, 19.8, "前面的话"),  # 重映射 18.0-20.16，与窗口重叠 0.16/2.16 → 丢
                _word(19.8, 20.2, "边界词"),    # 重映射 20.16-20.64，全在窗口内 → 留
                _word(20.2, 21.4, "今天天气"),  # 重映射 20.64-22.08，重叠 1.36/1.44 → 留
                _word(21.4, 23.0, "不错"),      # 重映射 22.08-24.0，与窗口零重叠 → 丢
            ],
        }
    ]
    cropped = export_api.crop_dialogue_lines(items, 20.0, 22.0)
    assert len(cropped) == 1
    line = cropped[0]
    assert line["text"] == "边界词今天天气"
    # 重定基：窗口 20.0 起点 → 段内相对秒
    assert line["start"] == pytest.approx(0.16)
    assert line["end"] == pytest.approx(2.0)
    # 跨界词钳到窗口起点，随后词顺次重定基
    assert [w["start"] for w in line["words"]] == pytest.approx([0.16, 0.64])
    assert [w["end"] for w in line["words"]] == pytest.approx([0.64, 2.0])


def test_crop_boundary_word_needs_majority_overlap() -> None:
    """跨界词按重叠过半归属：重叠 < 词长一半丢，≥ 一半留（FunClip 多数重叠思路）。

    行窗取成与词戳跨度一致（13.0），仿射退化成等比——本行只钉归属规则，不掺时钟换算。
    """
    items = [
        {
            "start": 9.0,
            "end": 13.0,
            "text": "甲乙",
            "words": [_word(9.0, 11.0, "甲"), _word(11.0, 13.0, "乙")],
        }
    ]
    # 窗口到 10.2：甲重叠 1.0/2.0 = 一半 → 留；窗口到 9.9：甲重叠 0.9/2.0 < 一半 → 丢
    kept = export_api.crop_dialogue_lines(items, 0.0, 10.2)
    assert kept and kept[0]["text"] == "甲"
    dropped = export_api.crop_dialogue_lines(items, 0.0, 9.9)
    assert dropped == []


def test_crop_burns_on_the_row_window_not_the_word_stamps() -> None:
    """两套时钟必须归一：行窗（=源字幕驻留窗，擦除读的就是它）才是显示时钟，词戳只供归属与行内比例。

    真机 ep1 实测（2026-10-10 立案④）：V4 行的词戳是把整段时长均分出来的插值，与行窗
    中位差 3.80s、最大 13.34s，23 行里 16 行的烧录窗与行窗**重叠为 0**——源字幕在屏时
    我们的字不在，我们的字在屏时源字幕已被擦掉（业主「不要到处乱跑」的同一条线）。
    """
    items = [
        {
            "start": 18.0,
            "end": 20.0,
            "text": "两句台词",
            "words": [_word(4.0, 5.0, "两句"), _word(5.0, 6.0, "台词")],  # 词戳比行窗早 14s
        }
    ]
    cropped = export_api.crop_dialogue_lines(items, 0.0, 30.0)
    assert [(c["start"], c["end"]) for c in cropped] == [(18.0, 20.0)]


def test_crop_partial_row_lands_inside_the_row_window() -> None:
    """段边界切开一行：留下的词按行窗比例占位——既不掉到窗外，也不因词戳漂移把台词整行丢掉。

    旧实现按原始词戳做归属：整行的词戳都落在段窗口之外时 kept 为空 → 这一行在成片里
    消失（台词缺失），而行窗明明就在窗口内。
    """
    items = [
        {
            "start": 10.0,
            "end": 14.0,
            "text": "甲乙",
            "words": [_word(20.0, 21.0, "甲"), _word(21.0, 22.0, "乙")],
        }
    ]
    # 重定基后 甲→10-12、乙→12-14；窗口 12-20 只装得下乙
    cropped = export_api.crop_dialogue_lines(items, 12.0, 20.0)
    assert [c["text"] for c in cropped] == ["乙"]
    assert (cropped[0]["start"], cropped[0]["end"]) == pytest.approx((0.0, 2.0))
    assert [w["start"] for w in cropped[0]["words"]] == pytest.approx([0.0])


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


# --- 台词时钟对账（立案④的可见化） --------------------------------------------


def test_clock_audit_counts_rows_without_dwell_counterpart() -> None:
    """段窗 20-30：行 1 绝对 22-26 与驻留窗 21-25 重叠，行 2 绝对 26-27 与任何窗零重叠。"""
    cropped = [
        {"start": 2.0, "end": 4.0, "text": "屏上有源字", "words": None},
        {"start": 6.0, "end": 7.0, "text": "屏上没源字", "words": None},
    ]
    assert export_api._clock_audit(cropped, 20.0, [(21.0, 25.0)]) == (2, 1)


def test_clock_audit_is_vacuous_without_dwell_windows() -> None:
    """驻留窗空表 = 编码端整段擦，两套时钟无从对照——记 (0, 0)，不许判成缺陷。

    真机库里 10 集 272 行有 24 行（8.8%）本就落在驻留窗外（纯 ASR 行/画外音），
    把「窗外」当缺陷拦片就是覆盖闸包含式判据拦 10 集的同款错误。
    """
    cropped = [{"start": 2.0, "end": 4.0, "text": "整段擦也无对照", "words": None}]
    assert export_api._clock_audit(cropped, 20.0, []) == (0, 0)


# --- render_export 集成 --------------------------------------------------------


def _seed(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    asr_items: list[dict[str, Any]] | None,
    *,
    seg_start: float = 20.0,
    seg_end: float = 30.0,
    mode: str = "intro_narration",
    ocr_items: list[dict[str, Any]] | None = None,
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
            ocr_segments=json.dumps(ocr_items) if ocr_items is not None else None,
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
    sent: list[dict[str, Any]] = []
    context = SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "cache",
        settings={"export.encoder": "libx264"},
        notifier=Notifier(sent.append),
        sent=sent,
    )
    return context, export_id, plan_row, plan_data


def _infos(context: SimpleNamespace) -> list[str]:
    return [
        str(m["params"]["message"])
        for m in context.sent  # type: ignore[attr-defined]
        if m["method"] == "log.append" and m["params"]["level"] == "info"
    ]


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


def test_render_logs_dialogue_clock_audit(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """烧录台词与驻留窗的对照关系要落成明账（立案④曾靠临时探针才看得见）。"""
    items = [
        {"start": 22.0, "end": 24.0, "text": "屏上有源字", "words": []},
        {"start": 26.0, "end": 27.0, "text": "屏上没源字", "words": []},
    ]
    context, export_id, plan_row, plan_data = _seed(
        memory_db, tmp_path, items, ocr_items=[{"start": 21.0, "end": 25.0, "text": "屏上有源字"}]
    )
    _render(monkeypatch, context, export_id, plan_row, plan_data)
    audit = [m for m in _infos(context) if "台词时钟对账" in m]
    assert len(audit) == 1, f"没出一条对账明账：{_infos(context)}"
    assert "烧录台词 2 行，可对照 2 行，其中 1 行" in audit[0], audit[0]


def test_render_reports_zero_comparable_rows_instead_of_passing(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """无驻留窗（整段擦）：账要记成「可对照 0 行」，不许沉默也不许假装对上。"""
    items = [{"start": 22.0, "end": 24.0, "text": "整段擦也有字", "words": []}]
    context, export_id, plan_row, plan_data = _seed(memory_db, tmp_path, items)
    _render(monkeypatch, context, export_id, plan_row, plan_data)
    audit = [m for m in _infos(context) if "台词时钟对账" in m]
    assert len(audit) == 1, f"没出一条对账明账：{_infos(context)}"
    assert "烧录台词 1 行，可对照 0 行" in audit[0], audit[0]
