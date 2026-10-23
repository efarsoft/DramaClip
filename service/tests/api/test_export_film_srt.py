"""H1 成片逐句时间轴：把段内相对字幕时刻搬到**成片坐标**，落成同名 `.srt`。

界面要能「点一句跳到那一秒」，靠的是段起点在成片里的偏移。偏移不能猜：
`timeline[].start/end` 是**源片集内时间**，`burn_subtitle`/`dialogue_subtitle`
烧的是**段内相对 0→窗口长**（`test_export_original_subtitles.py` 钉着 22s→2.00），
两个都不是成片刻度。唯一真相是 Phase B 拼接清单上各段产物的**实测时长**累加——
所以这里断言的是「第三句起于 12.0s」：既不是声明累计（11.0）、不是段内相对（1.0）、
也不是源片绝对（41.0）。

量不到偏移时**不产出文件**并记一条允许型降级（规格 §3.3.1「允许，但必须留痕」）：
半截或凑出来的时间轴会让界面把跳点跳到错的句子，比没有更坏，且看不出来。

`test_sidecar_srt_is_readable_by_the_ui_grammar` 是规格 §4.2 的侧车产物门禁：解不出＝这条
导出没交付完整。它刻意**不**复用写侧的 `format_srt`，而是按渲染层 `features/cues/srt.ts`
的 grammar 另写一份最小镜像——同一份实现自产自解只会把写坏的时间码认成通过。
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import export as export_api
from dramaclip.engines.exporter import encoder
from dramaclip.engines.narration.models import PlanData, TimelineSegment
from dramaclip.infra.ffmpeg import probe as probe_mod
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.notify import Notifier

# 段产物的实测时长：**故意不等于声明窗口长**（seg0 声明 10s、实测 11s），
# 这样"用声明值凑偏移"的错误实现会被时间轴断言抓住。
_MEASURED_S = {"seg_000.mp4": 11.0, "seg_001.mp4": 6.0}

_DIALOGUE = [
    {"start": 22.0, "end": 24.0, "text": "今天天气不错", "words": []},
    {"start": 41.0, "end": 42.5, "text": "我们出发吧", "words": []},
]


def _seed(
    memory_db: sqlite3.Connection, tmp_path: Path, *, mode: str = "intro_narration"
) -> tuple[SimpleNamespace, str, dict[str, Any], PlanData]:
    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    project_id = str(projects_repo.create(memory_db, "逐句剧", str(tmp_path))["id"])
    episodes_repo.replace_all(
        memory_db,
        project_id,
        [{"episode_number": 1, "source_path": str(source), "duration": 120.0}],
    )
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    analysis_repo.upsert(
        memory_db, episode_id, asr_segments=json.dumps(_DIALOGUE),
        scene_data=None, audio_features=None, ocr_segments=None,
    )
    plan_data = PlanData(
        mode=mode,
        timeline=[
            TimelineSegment(episode_id=episode_id, start=20.0, end=30.0, audio="original"),
            TimelineSegment(episode_id=episode_id, start=40.0, end=45.0, audio="original"),
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


def _render(
    monkeypatch: pytest.MonkeyPatch,
    context: SimpleNamespace,
    export_id: str,
    plan_row: dict[str, Any],
    plan_data: PlanData,
    *,
    measured: dict[str, float] | None = _MEASURED_S,
) -> Path:
    """桩掉切割/拼接/响度与段探测，走生产 render_export，返回成片路径。"""
    monkeypatch.setattr(encoder.jitter, "safe_times", lambda s, e, _z, **_k: (s, e))

    def _fake_cut(args: list[str], *_a: Any, **_k: Any) -> None:
        Path(args[-1]).write_bytes(b"seg")

    monkeypatch.setattr(encoder, "_run_cut", _fake_cut)
    monkeypatch.setattr(
        encoder, "_concat", lambda _files, target: Path(target).write_bytes(b"film")
    )
    monkeypatch.setattr(encoder.loudness, "normalize_in_place", lambda *_a, **_k: None)
    monkeypatch.setattr(export_api.ffmpeg_cover, "extract_cover", lambda *_a, **_k: False)

    def _probe(path: Path) -> probe_mod.MediaInfo:
        # `export_api.probe` 与 `encoder.ffprobe_mod` 是同一个模块对象，两处打桩会互相
        # 覆盖，所以一个函数分派：段产物给实测时长，别的（成片元信息）照旧抛。
        if measured is None or path.name not in measured:
            raise ValueError(f"探测桩：非段产物 {path.name}")
        return probe_mod.MediaInfo(
            duration_s=measured[path.name], width=1080, height=1920, fps=30.0, has_audio=True
        )

    monkeypatch.setattr(encoder.ffprobe_mod, "probe", _probe)
    out_path = export_api.render_export(
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
    return Path(out_path)


def _warns(context: SimpleNamespace) -> list[str]:
    return [
        str(m["params"]["message"])
        for m in context.sent  # type: ignore[attr-defined]
        if m["method"] == "log.append" and m["params"]["level"] == "warn"
    ]


def test_film_srt_uses_measured_concat_offsets(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """第二段起点＝第一段**实测** 11s：句 41.0s 在成片里是 12.0s，不是 1.0/11.0/41.0。"""
    context, export_id, plan_row, plan_data = _seed(memory_db, tmp_path)
    out = _render(monkeypatch, context, export_id, plan_row, plan_data)

    srt = out.with_suffix(".srt")
    assert srt.is_file(), f"烧了字幕就该有逐句时间轴旁挂产物：{srt}"
    text = srt.read_text(encoding="utf-8")
    assert "00:00:02,000 --> 00:00:04,000\n今天天气不错" in text, text
    assert "00:00:12,000 --> 00:00:13,500\n我们出发吧" in text, text
    assert "00:00:41" not in text and "00:00:01,000 --> " not in text, (
        f"时间轴混进了源片绝对时刻或段内相对时刻：{text}"
    )


def test_unmeasurable_offsets_leave_no_srt_and_trace_the_degradation(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """量不到偏移＝不产出 + 点名留痕，导出终态仍是 completed（允许型降级不挡交付）。"""
    context, export_id, plan_row, plan_data = _seed(memory_db, tmp_path)
    out = _render(monkeypatch, context, export_id, plan_row, plan_data, measured=None)

    assert not out.with_suffix(".srt").exists(), "凑出来的时间轴不许落盘"
    joined = "\n".join(_warns(context))
    assert "成片逐句时间轴" in joined, f"缺了这条账，界面只会显示空列表：{joined}"
    row = exports_repo.get(memory_db, export_id)
    assert row is not None and row["status"] == exports_repo.STATUS_COMPLETED, (
        "留痕不许把成功出片改成失败"
    )


def test_non_burning_mode_writes_no_srt_and_is_not_a_degradation(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """raw_clip 本来不烧字幕：没有时间轴是设计本意，不许记成降级、界面也不许报警。"""
    context, export_id, plan_row, plan_data = _seed(memory_db, tmp_path, mode="raw_clip")
    out = _render(monkeypatch, context, export_id, plan_row, plan_data)

    assert not out.with_suffix(".srt").exists()
    joined = "\n".join(_warns(context))
    assert "成片逐句时间轴" not in joined, f"纯原片被指控成降级：{joined}"


_STAMP = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})")


def _ui_parse(content: str) -> list[tuple[float, float, str]]:
    """渲染层 `features/cues/srt.ts` 的 `parseSrt` 的最小镜像（时间码越界整条弃）。

    写侧的 `format_srt` 不参与这里：门禁要判的是「界面读得开读不开」，
    用产出它的同一个模块解开它，格式改坏了也照样绿。
    """
    cues: list[tuple[float, float, str]] = []
    for block in content.replace("\r\n", "\n").split("\n\n"):
        lines = block.split("\n")
        if len(lines) > 1 and re.fullmatch(r"\d+", lines[0].strip()):
            lines = lines[1:]
        if len(lines) < 2:
            continue
        stamps = _STAMP.findall(lines[0])
        if len(stamps) != 2:
            continue
        seconds = [
            int(h) * 3600 + int(m) * 60 + int(s) + int(frac) / 1000
            for h, m, s, frac in stamps
        ]
        if any(int(m) > 59 or int(s) > 59 for _, m, s, _ in stamps):
            continue
        text = "\n".join(t for t in lines[1:] if t.strip() != "")
        if text == "":
            continue
        cues.append((seconds[0], seconds[1], text))
    return cues


def _burned_texts(ass_dir: Path) -> list[str]:
    """从段 ass 里读**真烧上去的**每行文本（Dialogue 行的正文，去掉覆盖标签）。"""
    texts: list[str] = []
    for path in sorted(ass_dir.glob("seg_*.ass")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("Dialogue:"):
                continue
            body = line.split(",", 9)[9]
            texts.append(re.sub(r"\{\\[^}]*\}", "", body).replace("\\N", ""))
    return texts


def test_sidecar_srt_is_readable_by_the_ui_grammar(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """§4.2 侧车产物门禁：界面 grammar 解得出 ≥1 句，句数与句序 == 段 ass 实烧行。

    只断言「文件存在」或「非空」拦不住写坏的时间码与漏掉的行——那种账落进界面就是
    点不开、或整条错位（§1.4 的假对齐）。这里以烧录产物本身为对照面。
    """
    context, export_id, plan_row, plan_data = _seed(memory_db, tmp_path)
    out = _render(monkeypatch, context, export_id, plan_row, plan_data)

    burned = _burned_texts(tmp_path / "cache" / "export" / export_id)
    cues = _ui_parse(out.with_suffix(".srt").read_text(encoding="utf-8"))
    assert len(cues) >= 1, "解不出＝这条导出没交付完整"
    assert [text for _s, _e, text in cues] == burned, "侧车句子与实烧台词不同一条链"
    assert cues[-1][1] <= sum(_MEASURED_S.values()), "末句越过了成片时长"
