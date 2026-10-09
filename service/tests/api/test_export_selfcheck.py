"""成片自检四项产品化（09-10 §4.5 / 接口改动点 #29）：判据、钩子、补测作业、列表透传。

纪律与 verify_modes.py 同源：宁灰勿假绿——量不到 pass=null，量到不过线才 false。
钩子是增强项：自检怎么坏都不得挡导出完成（与 _audit_duration/_extract_cover 同款）。
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import export as export_api
from dramaclip.engines.exporter import encoder, selfcheck
from dramaclip.engines.narration.models import PlanData, TimelineSegment
from dramaclip.infra import jobs as jobs_mod
from dramaclip.infra.ffmpeg import probe as probe_mod
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import Router, RpcRequest
from tests.conftest import register_job_executor

# 真机版式的 ffmpeg stderr 样例（volumedetect 尾部汇总 + freezedetect 两段静止）
_STDERR_BOTH = (
    "[Parsed_freezedetect_0 @ 000001] lavfi.freezedetect.freeze_start: 1.2\n"
    "[Parsed_freezedetect_0 @ 000001] lavfi.freezedetect.freeze_duration: 1.5\n"
    "[Parsed_freezedetect_0 @ 000001] lavfi.freezedetect.freeze_start: 8.0\n"
    "[Parsed_freezedetect_0 @ 000001] lavfi.freezedetect.freeze_duration: 3.2\n"
    "[Parsed_volumedetect_0 @ 000002] n_samples: 132300\n"
    "[Parsed_volumedetect_0 @ 000002] mean_volume: -23.4 dB\n"
    "[Parsed_volumedetect_0 @ 000002] max_volume: -3.1 dB\n"
)


def _fake_run(
    monkeypatch: pytest.MonkeyPatch, *, stderr: str, returncode: int = 0
) -> None:
    def run(*_a: Any, **_k: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=returncode, stdout="", stderr=stderr)

    monkeypatch.setattr(selfcheck.subprocess, "run", run)


# ---- 度量原语：一遍解码测两项 ----


def test_measure_parses_mean_and_max_freeze_from_one_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_run(monkeypatch, stderr=_STDERR_BOTH)
    video = tmp_path / "film.mp4"
    video.write_bytes(b"x")
    assert selfcheck.measure_audio_video(video) == (-23.4, 3.2)


def test_measure_without_freeze_lines_is_true_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """命令成功而没有 freeze_duration 行 = 真没静止段，是 0.0 不是缺测。"""
    _fake_run(monkeypatch, stderr="[Parsed_volumedetect_0 @ 0] mean_volume: -18.0 dB\n")
    video = tmp_path / "film.mp4"
    video.write_bytes(b"x")
    assert selfcheck.measure_audio_video(video) == (-18.0, 0.0)


def test_measure_failure_is_none_not_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """解码失败/超时 = 量不到（None, None），不是「静音/冻结」的判定。"""
    video = tmp_path / "film.mp4"
    video.write_bytes(b"x")
    _fake_run(monkeypatch, stderr="", returncode=1)
    assert selfcheck.measure_audio_video(video) == (None, None)

    def boom(*_a: Any, **_k: Any) -> None:
        raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=1)

    monkeypatch.setattr(selfcheck.subprocess, "run", boom)
    assert selfcheck.measure_audio_video(video) == (None, None)


def test_measure_real_sample_video(sample_video: Path) -> None:
    """真 bundled ffmpeg + 3s testsrc 正弦音轨：两项都量得出，正弦响度远高于 -70dB。"""
    mean_volume_db, max_freeze_s = selfcheck.measure_audio_video(sample_video)
    assert mean_volume_db is not None and mean_volume_db > selfcheck.MIN_MEAN_VOLUME_DB
    assert max_freeze_s is not None and max_freeze_s < selfcheck.MAX_FREEZE_S


# ---- 四项判据真值表 ----


def test_check_duration_truth_table() -> None:
    assert selfcheck.check_duration(None, 30.0)["pass"] is None
    assert selfcheck.check_duration(30.0, None)["pass"] is None
    assert selfcheck.check_duration(30.0, 0.0)["pass"] is None
    ok = selfcheck.check_duration(31.5, 30.0)  # +5% 在 max(8%,3s) 内
    assert ok["pass"] is True and ok["measured_s"] == 31.5 and ok["budget_s"] == 30.0
    assert selfcheck.check_duration(27.5, 30.0)["pass"] is True  # -8.3% 但绝对差 2.5s < 3s 地板
    assert selfcheck.check_duration(60.0, 30.0)["pass"] is False


def test_check_narration_truth_table() -> None:
    # 无旁白模式：有音轨即过，音轨缺失是实打实的红
    none_ok = selfcheck.check_narration(True, "raw_clip", None)
    assert none_ok["pass"] is True and none_ok["expected"] == "none"
    assert selfcheck.check_narration(False, "subtitle_flow", None)["pass"] is False
    # 解说类：方案缺失归灰；floor 同 verify_modes（one≥1，many≥2）
    grey = selfcheck.check_narration(True, "full_narration", None)
    assert grey["pass"] is None
    assert selfcheck.check_narration(True, "full_narration", 8)["pass"] is True
    assert selfcheck.check_narration(True, "full_narration", 1)["pass"] is False
    assert selfcheck.check_narration(True, "intro_narration", 1)["pass"] is True
    assert selfcheck.check_narration(False, "full_narration", 8)["pass"] is False


def test_check_silence_and_freeze_truth_table() -> None:
    no_audio = selfcheck.check_silence(None, False)
    assert no_audio["pass"] is False and no_audio["reason"] == "无音轨"
    assert selfcheck.check_silence(None, True)["pass"] is None
    assert selfcheck.check_silence(-70.0, True)["pass"] is True  # 阈值含等号
    assert selfcheck.check_silence(-70.1, True)["pass"] is False
    assert selfcheck.check_freeze(None)["pass"] is None
    assert selfcheck.check_freeze(1.9)["pass"] is True
    assert selfcheck.check_freeze(2.0)["pass"] is False  # verify_modes 用 >= 判红的反面
    assert selfcheck.check_freeze(0.0)["pass"] is True


def test_overall_state_three_words() -> None:
    def checks(*flags: bool | None) -> dict[str, Any]:
        names = ("duration", "narration", "silence", "freeze")
        return dict(zip(names, [{"pass": f} for f in flags], strict=True))

    assert selfcheck.overall_state(checks(True, True, True, True)) == "passed"
    assert selfcheck.overall_state(checks(True, False, True, True)) == "failed"
    assert selfcheck.overall_state(checks(True, None, True, True)) == "partial"
    assert selfcheck.overall_state(checks(None, None, None, None)) == "partial"


def test_run_payload_shape(sample_video: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selfcheck, "measure_audio_video", lambda _v: (-20.0, 0.5))
    payload = selfcheck.run(
        sample_video, measured_s=3.0, has_audio=True, mode="raw_clip",
        budget_s=3.0, planned_segments=None,
    )
    assert payload["version"] == 1 and payload["checked_at"] > 0
    assert selfcheck.overall_state(payload) == "passed"
    assert json.loads(json.dumps(payload))["freeze"]["max_freeze_s"] == 0.5


# ---- 画面侧度量：成片文字落位 vs 覆盖承诺（业主裁决④）----


def test_measure_caption_band_reuses_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """度量原语直通透传 detect_band 的参数（带=成片里 OCR 到的文字带）。"""
    seen: dict[str, Any] = {}

    def fake_detect(video: Path, work_dir: Path, **kwargs: Any) -> tuple[float, float]:
        seen["video"] = video
        seen["work_dir"] = work_dir
        seen.update(kwargs)
        return (0.81, 0.91)

    monkeypatch.setattr(selfcheck.subtitle_ocr, "detect_band", fake_detect)
    film = tmp_path / "film.mp4"
    film.write_bytes(b"x")
    measured = selfcheck.measure_caption_band(film, work_dir=tmp_path / "w", duration_s=30.0)
    assert measured == (0.81, 0.91)
    assert seen == {"video": film, "work_dir": tmp_path / "w", "duration_s": 30.0, "ocr": None}


def test_measure_caption_band_unusable_ocr_is_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OCR 依赖没装/探测崩 = 量不到（None），不是「落位错」的判定——自检绝不炸批。"""

    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("rapidocr 未安装")

    monkeypatch.setattr(selfcheck.subtitle_ocr, "detect_band", boom)
    assert (
        selfcheck.measure_caption_band(
            tmp_path / "film.mp4", work_dir=tmp_path / "w", duration_s=30.0
        )
        is None
    )


def test_check_caption_placement_truth_table() -> None:
    # 没承诺（无带/带被判误检）与量不到都是灰，不判
    assert selfcheck.check_caption_placement((0.8, 0.9), None)["pass"] is None
    assert selfcheck.check_caption_placement(None, (0.8, 0.9))["pass"] is None
    # 中心对齐 → 绿
    ok = selfcheck.check_caption_placement((0.79, 0.91), (0.80, 0.90))
    assert ok["pass"] is True and ok["center_offset"] == 0.0
    # 容差 = 承诺带半高 + 量的抖动：贴边算盖住，越出去一行算漂
    edge = selfcheck.check_caption_placement((0.86, 0.98), (0.80, 0.90))
    assert edge["center_offset"] == 0.07 and edge["cover_tolerance"] == 0.07
    assert edge["pass"] is True, "阈值含等号：实测中心正好压在容差线上 = 盖住"
    drift = selfcheck.check_caption_placement((0.87, 0.99), (0.80, 0.90))
    assert drift["pass"] is False and drift["center_offset"] == 0.08
    assert drift["cover_tolerance"] == 0.07
    # 悬空画面中部：真机反馈的缺陷形状，红且把两组数都记进成绩单
    red = selfcheck.check_caption_placement((0.40, 0.52), (0.80, 0.90))
    assert red["pass"] is False
    assert red["measured_top"] == 0.4 and red["expected_bottom"] == 0.9
    # 结论必须能从成绩单里那几个数复算出来——否则「记录 0.07/0.07 却判红」无法解释
    for measured, expected in (
        ((0.86, 0.98), (0.80, 0.90)),
        ((0.87, 0.99), (0.80, 0.90)),
        ((0.79, 0.91), (0.80, 0.90)),
    ):
        item = selfcheck.check_caption_placement(measured, expected)
        assert item["pass"] is (abs(item["center_offset"]) <= item["cover_tolerance"])


def test_run_measures_caption_only_when_promise_exists(
    sample_video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """成本纪律：没有覆盖承诺的片子不付成片 OCR 的账。"""
    monkeypatch.setattr(selfcheck, "measure_audio_video", lambda _v: (-20.0, 0.5))
    calls: list[tuple[Any, ...]] = []

    def fake_measure(*args: Any, **kwargs: Any) -> tuple[float, float]:
        calls.append((args, kwargs))
        return (0.80, 0.92)

    monkeypatch.setattr(selfcheck, "measure_caption_band", fake_measure)
    work_dir = sample_video.parent / "cache"
    grey = selfcheck.run(
        sample_video, measured_s=3.0, has_audio=True, mode="raw_clip",
        budget_s=3.0, planned_segments=None, work_dir=work_dir,
    )
    assert grey["caption_placement"]["pass"] is None and calls == []

    judged = selfcheck.run(
        sample_video, measured_s=3.0, has_audio=True, mode="raw_clip",
        budget_s=3.0, planned_segments=None,
        caption_band=(0.79, 0.91), work_dir=work_dir,
    )
    assert judged["caption_placement"]["pass"] is True
    assert len(calls) == 1, "有承诺才测一次"

    nowhere = selfcheck.run(
        sample_video, measured_s=3.0, has_audio=True, mode="raw_clip",
        budget_s=3.0, planned_segments=None,
        caption_band=(0.79, 0.91),
    )
    assert nowhere["caption_placement"]["pass"] is None and len(calls) == 1, (
        "有承诺但没落点目录 = 探针帧没地方放，灰着不猜（run 的 work_dir 是可选形参，"
        "缺省调用不许炸自检）"
    )

    no_duration = selfcheck.run(
        sample_video, measured_s=None, has_audio=True, mode="raw_clip",
        budget_s=3.0, planned_segments=None,
        caption_band=(0.79, 0.91), work_dir=work_dir,
    )
    assert no_duration["caption_placement"]["pass"] is None and len(calls) == 1, (
        "成片时长没探到 = 抽帧位置无从算起，不拿 None 去喂探测器"
    )


def test_overall_state_keeps_four_items() -> None:
    """画面侧那一项不进交付四项汇总：四项徽章语义不变（红由徽章自己呈现）。"""
    base = {name: {"pass": True} for name in ("duration", "narration", "silence", "freeze")}
    base["caption_placement"] = {"pass": False}
    assert selfcheck.overall_state(base) == "passed"


def test_plan_cover_promise_only_for_promised_shapes(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """自检基准只收生成端真承诺的形状（判据与渲染端同源，两处不各写一份）。"""
    context, _export_id, plan_row, plan_data = _seed_render(memory_db, tmp_path)
    episode_id = str(
        episodes_repo.list_by_project(memory_db, str(plan_row["project_id"]))[0]["id"]
    )
    analysis_repo.upsert(
        memory_db, episode_id, asr_segments="[]", scene_data=None, audio_features=None
    )

    def promise(raw: str | None) -> Any:
        if raw is not None:
            analysis_repo.update_subtitle_band(memory_db, episode_id, raw)
        return export_api._plan_cover_promise(context, plan_data)

    assert promise(json.dumps([0.135, 0.816])) is None, "带高 68% = 满幅误检，本就没承诺"
    assert promise(json.dumps([0.1, 0.3])) is None, "带心在上半 = 2/3 封顶辖区，不是覆盖承诺"
    assert promise(json.dumps([0.80, 0.90])) == (0.80, 0.90), "旧格式（纯 list 带）照收"
    assert promise(json.dumps({"band": [0.60, 0.95], "lines": [[0.80, 0.90]]})) == (
        0.80,
        0.90,
    ), "新格式收行框并集，不收整带包络"
    assert promise(json.dumps({"band": [0.70, 0.90], "lines": [[0.09, 0.26]]})) == (
        0.70,
        0.90,
    ), "花字行不采信 → 回退整带"
    # 坏形状一律不进承诺面（落库列是自由 JSON，布尔/单元素/坏文本都能出现）
    assert promise(json.dumps([True, False])) is None, "布尔不是坐标"
    assert promise(json.dumps([0.8])) is None, "单元素不是区间"
    assert promise("{not json") is None, "坏 JSON = 没探过，不是判红"


def test_plan_cover_promise_unions_episodes_and_drops_unpromiseable(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """跨集取并集当基准；并集被撑成没承诺的形状（异画幅/远距台词带）归灰不判红。"""
    source = tmp_path / "ep.mp4"
    source.write_bytes(b"x")
    project_id = str(projects_repo.create(memory_db, "跨集剧", str(tmp_path))["id"])
    episodes_repo.replace_all(
        memory_db,
        project_id,
        [
            {"episode_number": 1, "source_path": str(source), "duration": 120.0},
            {"episode_number": 2, "source_path": str(source), "duration": 120.0},
        ],
    )
    ids = [str(ep["id"]) for ep in episodes_repo.list_by_project(memory_db, project_id)]
    for episode_id, band in zip(ids, [(0.74, 0.84), (0.80, 0.90)], strict=True):
        analysis_repo.upsert(
            memory_db, episode_id, asr_segments="[]", scene_data=None, audio_features=None
        )
        analysis_repo.update_subtitle_band(memory_db, episode_id, json.dumps(band))
    plan_data = PlanData(
        mode="raw_clip",
        timeline=[
            TimelineSegment(episode_id=ids[0], start=0.0, end=10.0, audio="original"),
            TimelineSegment(episode_id=ids[1], start=0.0, end=10.0, audio="original"),
        ],
    )
    context = SimpleNamespace(conn=memory_db, data_dir=tmp_path, work_dir=tmp_path / "cache")
    assert export_api._plan_cover_promise(context, plan_data) == (0.74, 0.90)

    # 第 2 集换成上半带：它自己不算承诺，并集只剩第 1 集那条
    analysis_repo.update_subtitle_band(memory_db, ids[1], json.dumps([0.1, 0.2]))
    assert export_api._plan_cover_promise(context, plan_data) == (0.74, 0.84)

    # 两集各在自己那半都算承诺，但并集 (0.52,0.90) 高 38% 超过误检线：不判（宁灰不冤枉红）
    analysis_repo.update_subtitle_band(memory_db, ids[1], json.dumps([0.84, 0.90]))
    assert export_api._plan_cover_promise(context, plan_data) == (0.74, 0.90)
    analysis_repo.update_subtitle_band(memory_db, ids[0], json.dumps([0.52, 0.58]))
    assert export_api._plan_cover_promise(context, plan_data) is None


# ---- 完成钩子：导出尾部自动落成绩单，坏了不挡导出 ----


def _seed_render(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> tuple[SimpleNamespace, str, dict[str, Any], PlanData]:
    """种项目 + 一集 + 声明 30s 的 raw_clip 编排（形状同 test_export_audit._seed）。"""
    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    project_id = str(projects_repo.create(memory_db, "自检剧", str(tmp_path))["id"])
    episodes_repo.replace_all(
        memory_db, project_id,
        [{"episode_number": 1, "source_path": str(source), "duration": 120.0}],
    )
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    plan_data = PlanData(
        mode="raw_clip",
        timeline=[
            TimelineSegment(episode_id=episode_id, start=0.0, end=10.0, audio="original"),
            TimelineSegment(episode_id=episode_id, start=20.0, end=40.0, audio="original"),
        ],
    )
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
    actual_duration_s: float = 30.0,
) -> Path:
    """桩掉 ffmpeg 执行链与 probe（test_export_audit 同款），走生产入口 render_export。"""
    monkeypatch.setattr(encoder, "_run_cut", lambda *_a, **_k: None)

    def _fake_concat(_files: list[Path], target: Path) -> None:
        Path(target).write_bytes(b"film")

    monkeypatch.setattr(encoder, "_concat", _fake_concat)
    monkeypatch.setattr(encoder.loudness, "normalize_in_place", lambda *_a, **_k: None)
    monkeypatch.setattr(export_api.ffmpeg_cover, "extract_cover", lambda *_a, **_k: False)
    monkeypatch.setattr(
        export_api.probe, "probe",
        lambda _p: probe_mod.MediaInfo(
            duration_s=actual_duration_s, width=1080, height=1920, fps=30.0, has_audio=True
        ),
    )
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


def test_completion_hook_writes_passed_report(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    context, export_id, plan_row, plan_data = _seed_render(memory_db, tmp_path)
    monkeypatch.setattr(selfcheck, "measure_audio_video", lambda _v: (-20.0, 0.5))
    _render(monkeypatch, context, export_id, plan_row, plan_data, actual_duration_s=30.0)

    row = exports_repo.get(memory_db, export_id)
    assert row is not None and row["selfcheck_state"] == "passed"
    payload = json.loads(str(row["selfcheck"]))
    assert payload["duration"]["pass"] is True
    assert payload["narration"]["expected"] == "none" and payload["narration"]["pass"] is True
    assert payload["silence"]["mean_volume_db"] == -20.0
    assert payload["freeze"]["max_freeze_s"] == 0.5


def test_completion_hook_reports_red_without_blocking(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """实测 60s vs 声明 30s + 冻结 3.2s：成绩单如实红，导出记录仍 completed。"""
    context, export_id, plan_row, plan_data = _seed_render(memory_db, tmp_path)
    monkeypatch.setattr(selfcheck, "measure_audio_video", lambda _v: (-20.0, 3.2))
    _render(monkeypatch, context, export_id, plan_row, plan_data, actual_duration_s=60.0)

    row = exports_repo.get(memory_db, export_id)
    assert row is not None and row["status"] == exports_repo.STATUS_COMPLETED
    assert row["selfcheck_state"] == "failed"
    payload = json.loads(str(row["selfcheck"]))
    assert payload["duration"]["pass"] is False and payload["freeze"]["pass"] is False


def test_completion_hook_records_caption_placement(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """库里有采信带 → 出片尾部量画面侧：承诺 (0.80,0.90)、成片量到 (0.81,0.91) → 绿。

    四项汇总不受它影响（`_ITEMS` 仍是四项），但数必须落进成绩单——「字幕到处乱跑」
    这件事从此有实测数，不靠肉眼。
    """
    context, export_id, plan_row, plan_data = _seed_render(memory_db, tmp_path)
    episode_id = str(
        episodes_repo.list_by_project(memory_db, str(plan_row["project_id"]))[0]["id"]
    )
    analysis_repo.upsert(
        memory_db, episode_id, asr_segments="[]", scene_data=None, audio_features=None
    )
    assert analysis_repo.update_subtitle_band(
        memory_db, episode_id, json.dumps({"band": [0.70, 0.95], "lines": [[0.80, 0.90]]})
    ), "种数据没种上，这条用例等于没测"
    monkeypatch.setattr(selfcheck, "measure_audio_video", lambda _v: (-20.0, 0.5))
    monkeypatch.setattr(selfcheck, "measure_caption_band", lambda *_a, **_k: (0.81, 0.91))
    _render(monkeypatch, context, export_id, plan_row, plan_data)

    row = exports_repo.get(memory_db, export_id)
    assert row is not None and row["selfcheck_state"] == "passed"
    payload = json.loads(str(row["selfcheck"]))
    caption = payload["caption_placement"]
    assert caption["pass"] is True
    assert caption["expected_top"] == 0.8 and caption["expected_bottom"] == 0.9
    assert caption["measured_top"] == 0.81


def test_completion_hook_caption_grey_without_band(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """无覆盖承诺（库里没带）→ 画面侧那一项灰，且不去跑成片 OCR。"""
    context, export_id, plan_row, plan_data = _seed_render(memory_db, tmp_path)

    def boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("无承诺不该量画面侧")

    monkeypatch.setattr(selfcheck, "measure_audio_video", lambda _v: (-20.0, 0.5))
    monkeypatch.setattr(selfcheck, "measure_caption_band", boom)
    _render(monkeypatch, context, export_id, plan_row, plan_data)

    row = exports_repo.get(memory_db, export_id)
    assert row is not None and row["selfcheck_state"] == "passed"
    payload = json.loads(str(row["selfcheck"]))
    assert payload["caption_placement"]["pass"] is None


def test_selfcheck_crash_never_blocks_export(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    def boom(_v: Path) -> tuple[float | None, float | None]:
        raise RuntimeError("度量管线炸了")

    context, export_id, plan_row, plan_data = _seed_render(memory_db, tmp_path)
    monkeypatch.setattr(selfcheck, "measure_audio_video", boom)
    out = _render(monkeypatch, context, export_id, plan_row, plan_data)

    assert out.is_file()
    row = exports_repo.get(memory_db, export_id)
    assert row is not None and row["status"] == exports_repo.STATUS_COMPLETED
    assert row["selfcheck"] is None, "量不到就不发成绩单——NULL 而不是假绿"


def test_retry_reset_clears_stale_report(memory_db: sqlite3.Connection) -> None:
    """旧成绩单描述的是旧产物：重试复位必须一并作废，否则 pending 期间挂着假绿灯。"""
    project_id = str(projects_repo.create(memory_db, "复位剧", "D:/x")["id"])
    plan_id = str(plans_repo.create(memory_db, project_id, "raw_clip", [], {"timeline": []})["id"])
    export_id = exports_repo.create(memory_db, project_id, plan_id, "raw_clip")
    exports_repo.mark_completed(memory_db, export_id, "D:/out/a.mp4")
    exports_repo.set_selfcheck(memory_db, export_id, '{"version":1}', "passed")
    exports_repo.mark_failed(memory_db, export_id, "编码失败")
    assert exports_repo.reset_for_retry(memory_db, export_id)
    row = exports_repo.get(memory_db, export_id)
    assert row is not None and row["selfcheck"] is None and row["selfcheck_state"] is None


# ---- export.selfcheck：历史成片补测（job 化，幂等） ----


def _harness(memory_db: sqlite3.Connection, tmp_path: Path) -> SimpleNamespace:
    context = SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "cache",
        settings={},
        notifier=Notifier(lambda _m: None),
        executor=register_job_executor(ThreadPoolExecutor(max_workers=2)),
        job_store=jobs_mod.JobStore(memory_db),
        cancel_events={},
    )
    router = Router()
    export_api.register(router, context)  # type: ignore[arg-type]
    return SimpleNamespace(context=context, router=router)


def _rpc(harness: SimpleNamespace, method: str, params: dict[str, Any]) -> Any:
    response = harness.router.dispatch(RpcRequest(id=method, method=method, params=params))
    if response.error is not None:
        raise AssertionError(f"{method} RPC 错误: [{response.error.code}] {response.error.message}")
    return response.result


def _seed_completed_work(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> str:
    """一条已完成成片：产物是真视频文件（probe 要真探），方案声明 3s raw_clip。"""
    project_id = str(projects_repo.create(memory_db, "补测剧", str(tmp_path))["id"])
    plan_data = {
        "mode": "raw_clip",
        "timeline": [{"episode_id": "e", "start": 0.0, "end": 3.0, "audio": "original"}],
    }
    plan_id = str(plans_repo.create(memory_db, project_id, "raw_clip", [], plan_data)["id"])
    export_id = exports_repo.create(memory_db, project_id, plan_id, "raw_clip")
    out_dir = tmp_path / "outputs" / project_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "film.mp4"
    shutil.copy(sample_video, out_path)
    exports_repo.mark_completed(memory_db, export_id, str(out_path))
    return export_id


def test_selfcheck_batch_backfills_and_is_idempotent(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(selfcheck, "measure_audio_video", lambda _v: (-20.0, 0.5))
    harness = _harness(memory_db, tmp_path)
    export_id = _seed_completed_work(memory_db, tmp_path, sample_video)

    result = _rpc(harness, "export.selfcheck", {})
    assert result["queued"] == 1 and result["job_id"]
    harness.context.executor.shutdown(wait=True)

    job_row = harness.context.job_store.get(str(result["job_id"]))
    assert job_row is not None and job_row["type"] == "export_selfcheck"
    assert job_row["status"] == "completed"
    row = exports_repo.get(memory_db, export_id)
    assert row is not None and row["selfcheck_state"] == "passed"

    # 幂等：已有成绩单的行不再进补测队列（queued=0 在提交作业前返回，死池也无妨）
    assert _rpc(harness, "export.selfcheck", {})["queued"] == 0
    # 显式 export_ids = 重测（已有成绩单也覆盖重跑）；换新 harness = 新执行池
    harness2 = _harness(memory_db, tmp_path)
    result2 = _rpc(harness2, "export.selfcheck", {"export_ids": [export_id]})
    assert result2["queued"] == 1 and result2["job_id"]
    harness2.context.executor.shutdown(wait=True)
    row2 = exports_repo.get(memory_db, export_id)
    assert row2 is not None and row2["selfcheck_state"] == "passed"


def test_selfcheck_batch_skips_rows_without_file(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """记录指向的产物不在盘上：不进队列（queued=0），保持 NULL 诚实。"""
    harness = _harness(memory_db, tmp_path)
    project_id = str(projects_repo.create(memory_db, "空剧", str(tmp_path))["id"])
    plan_id = str(plans_repo.create(memory_db, project_id, "raw_clip", [], {"timeline": []})["id"])
    export_id = exports_repo.create(memory_db, project_id, plan_id, "raw_clip")
    exports_repo.mark_completed(memory_db, export_id, str(tmp_path / "gone.mp4"))
    assert _rpc(harness, "export.selfcheck", {})["queued"] == 1  # 队列按行收，盘上验证在作业体
    harness.context.executor.shutdown(wait=True)
    row = exports_repo.get(memory_db, export_id)
    assert row is not None and row["selfcheck"] is None


# ---- list_works：解码透传 + 自检筛选（#30） ----


def test_list_works_carries_decoded_selfcheck_and_trace(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    project_id = str(projects_repo.create(memory_db, "透传剧", str(tmp_path))["id"])
    plan_id = str(
        plans_repo.create(
            memory_db, project_id, "full_narration", ["ep1", "ep2"],
            {"mode": "full_narration", "timeline": []}, angle="替身真相",
        )["id"]
    )
    export_id = exports_repo.create(memory_db, project_id, plan_id, "full_narration")
    exports_repo.mark_completed(memory_db, export_id, str(tmp_path / "a.mp4"))
    report = json.dumps({"version": 1, "freeze": {"pass": True}})
    exports_repo.set_selfcheck(memory_db, export_id, report, "passed")
    other = exports_repo.create(memory_db, project_id, plan_id, "full_narration")
    exports_repo.mark_completed(memory_db, other, str(tmp_path / "b.mp4"))

    harness = _harness(memory_db, tmp_path)
    works = _rpc(harness, "export.list_works", {})
    assert len(works) == 2
    by_id = {work["id"]: work for work in works}
    checked = by_id[export_id]
    assert checked["selfcheck"]["freeze"]["pass"] is True, "selfcheck 必须解码成对象而非 JSON 串"
    assert checked["selfcheck_state"] == "passed"
    assert checked["angle"] == "替身真相"
    assert checked["episode_ids"] == ["ep1", "ep2"]
    assert checked["narration_plan_id"] == plan_id
    assert by_id[other]["selfcheck"] is None and by_id[other]["selfcheck_state"] is None

    passed = _rpc(harness, "export.list_works", {"state": "passed"})
    assert [work["id"] for work in passed] == [export_id]
    unchecked = _rpc(harness, "export.list_works", {"state": "unchecked"})
    assert [work["id"] for work in unchecked] == [other]
    bogus = _rpc(harness, "export.list_works", {"state": "词表外"})
    assert len(bogus) == 2, "词表外的筛选值当作不筛，不报错"
