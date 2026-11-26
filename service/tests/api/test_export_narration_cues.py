"""词界 → 解说字幕行的接线：`render_export` 烧出来的 ASS 用的是真实词时。

纯函数各自有测试（`test_narration_lines`），这里钉的是断在中间的**接线**：
配音旁的 .cues.json 被读到、行时间进了段级 ass、并原样搬进成片逐句时间轴。
此前这条路径从未被真正触发过（引擎没要词界，边车不存在），所以没有一条测试看过它。
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from tests.api.test_export_band_wiring import _ass_file, _seed_narrated
from tests.api.test_export_film_srt import _render, _ui_parse

_TEXT = "六千六百六十六都掏了，新娘却连车门都不肯上——这场婚礼还能不能成？"
_LINES = ["六千六百六十六都掏了", "新娘却连车门都不肯上", "这场婚礼还能不能成？"]
# 真配音实测的词界（edge-tts 7.3.1）：不带标点，还在词中间断开
_CUES: list[dict[str, Any]] = [
    {"text": "六千六百六", "start": 0.1, "end": 1.125},
    {"text": "十六都", "start": 1.225, "end": 1.725},
    {"text": "掏", "start": 1.725, "end": 1.988},
    {"text": "了", "start": 1.988, "end": 2.163},
    {"text": "新娘", "start": 2.538, "end": 2.987},
    {"text": "却", "start": 3.0, "end": 3.125},
    {"text": "连", "start": 3.125, "end": 3.288},
    {"text": "车门", "start": 3.3, "end": 3.763},
    {"text": "都", "start": 3.85, "end": 3.962},
    {"text": "不肯", "start": 3.975, "end": 4.263},
    {"text": "上", "start": 4.263, "end": 4.513},
    {"text": "这", "start": 4.9, "end": 5.062},
    {"text": "场", "start": 5.062, "end": 5.225},
    {"text": "婚礼", "start": 5.237, "end": 5.725},
    {"text": "还", "start": 5.825, "end": 5.975},
    {"text": "能", "start": 5.975, "end": 6.088},
    {"text": "不能", "start": 6.1, "end": 6.375},
    {"text": "成", "start": 6.375, "end": 6.688},
]
_REAL_TIMES = [(0.1, 2.163), (2.538, 4.513), (4.9, 6.688)]
#: ASS 时间码只到厘秒
_CS = 0.011

_STAMP = re.compile(r"(\d+):(\d{2}):(\d{2})\.(\d{2})")


def _events(ass: str) -> list[tuple[float, float, str]]:
    """段级 ass 里每条 Dialogue 的 (起, 止, 文字)，时间按 ASS 的厘秒换成秒。"""

    def to_seconds(stamp: str) -> float:
        _h, minutes, seconds, centis = (int(part) for part in _STAMP.findall(stamp)[0])
        return minutes * 60 + seconds + centis / 100

    events = []
    for line in ass.splitlines():
        if line.startswith("Dialogue:"):
            fields = line.split(",", 9)
            events.append(
                (to_seconds(fields[1]), to_seconds(fields[2]), re.sub(r"\{[^{}]*\}", "", fields[9]))
            )
    return events


def _render_narrated(
    monkeypatch: pytest.MonkeyPatch,
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    text: str,
    cues: list[Any] | None,
) -> tuple[list[tuple[float, float, str]], Path]:
    """一段旁白的方案渲染一遍：文案换成给定的，配音旁按需放词界边车（None＝不放）。

    返回 (段级 ass 里的实烧行, 成片路径)。段产物时长按实测 10 秒，逐句时间轴才有刻度。
    """
    context, export_id, plan_row, plan_data, _episode_id = _seed_narrated(memory_db, tmp_path)
    plan_data.timeline[0].subtitle_text = text
    plan_data.narration_texts[0].text = text
    sidecar = Path(str(plan_data.narration_texts[0].audio_path)).with_name("intro.cues.json")
    if cues is None:
        sidecar.unlink(missing_ok=True)
    else:
        sidecar.write_text(json.dumps(cues, ensure_ascii=False), encoding="utf-8")
    film = _render(
        monkeypatch, context, export_id, plan_row, plan_data, measured={"seg_000.mp4": 10.0}
    )
    return _events(_ass_file(context, export_id).read_text(encoding="utf-8")), film


def _same_times(
    events: list[tuple[float, float, str]], expected: list[tuple[float, float]]
) -> bool:
    return all(
        abs(a - c) < _CS and abs(b - d) < _CS
        for (a, b, _t), (c, d) in zip(events, expected, strict=True)
    )


def test_burned_lines_follow_real_word_times(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    events, _film = _render_narrated(monkeypatch, memory_db, tmp_path, _TEXT, _CUES)

    assert [text for _s, _e, text in events] == _LINES
    assert _same_times(events, _REAL_TIMES)


def test_without_cues_lines_fall_back_to_character_share(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    events, _film = _render_narrated(monkeypatch, memory_db, tmp_path, _TEXT, None)

    assert [text for _s, _e, text in events] == _LINES
    # 三行各十字：按比例均分、首尾相接；与真实词时（第二行 2.538 秒才起）不是一回事
    assert all(abs(a[1] - b[0]) < _CS for a, b in zip(events, events[1:], strict=False))
    assert abs(events[1][0] - 3.333) < _CS and abs(events[1][0] - 2.538) > 0.5


def test_an_empty_sidecar_means_no_cues_not_a_crash(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """补词界补不到会留下空边车：它与没有边车同档，不许把它读成「零行」。"""
    events, _film = _render_narrated(monkeypatch, memory_db, tmp_path, _TEXT, [])

    assert [text for _s, _e, text in events] == _LINES


def test_a_short_last_line_is_held_long_enough_to_read(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """末行只有三个字、念了 0.4 秒：延末点到读得过来（0.8 秒），不动起点。"""
    text = "她把那本浸了水的婚书撕得粉碎，她走了。"
    cues = [
        {"text": "她把那本浸了水的婚书撕得粉碎", "start": 0.1, "end": 3.0},
        {"text": "她", "start": 3.4, "end": 3.5},
        {"text": "走", "start": 3.5, "end": 3.7},
        {"text": "了", "start": 3.7, "end": 3.8},
    ]

    events, _film = _render_narrated(monkeypatch, memory_db, tmp_path, text, cues)

    assert [text for _s, _e, text in events] == ["她把那本浸了水的婚书撕得粉碎", "她走了"]
    assert _same_times(events, [(0.1, 3.0), (3.4, 4.2)])


def test_word_times_reach_the_film_timeline_sidecar(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """逐句时间轴（界面「点一句跳一秒」的刻度）与实烧行是同一条链。"""
    _events_, film = _render_narrated(monkeypatch, memory_db, tmp_path, _TEXT, _CUES)

    cues = _ui_parse(film.with_suffix(".srt").read_text(encoding="utf-8"))
    assert [text for _s, _e, text in cues] == _LINES
    assert _same_times([(start, end, text) for start, end, text in cues], _REAL_TIMES)


def test_events_helper_reads_ass_timestamps() -> None:
    """夹具自检：厘秒时间码解析对不对，拿一条手写的 ass 行验。"""
    line = "Dialogue: 0,0:01:02.05,0:01:03.79,DC,,0,0,0,,{\\an2}她走了"
    assert _events(line) == [(62.05, 63.79, "她走了")]
