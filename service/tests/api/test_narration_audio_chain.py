"""全片解说旁白音轨的可达性：回填 → 段→音映射 → 混音命令，一条链跑通。

回归动机（两轴审查的阻断项）：三处代码对「哪些段有旁白」各说各话 ——
`modes_w8.py` 把每段标成 `ducked`、`pipeline.py` 回填只认 `narration`、
`api/export.py` 取音只认 `narration`。结果 `encoder.py` 里同时认
`narration`/`ducked` 的混音分支永远拿不到 `tts_audio`，成为
「看着已修、其实够不着」的死代码，`full_narration` 出厂零解说音。
本文件走的是生产入口 `render_export`（plan_data 经库内 JSON 往返），
只桩掉 TTS 与 ffmpeg 执行，任何一环断开都会红。
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import export as export_api
from dramaclip.engines.exporter import encoder
from dramaclip.engines.narration import pipeline
from dramaclip.engines.narration.casting import stamp
from dramaclip.engines.narration.models import PlanData, StrategySpec
from dramaclip.engines.narration.modes_w8 import build_full
from dramaclip.engines.semantic.models import ConflictScore
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo

_TTS_DURATION_S = 1.25


class _StubTts:
    """每段旁白落成各自的 mp3，文件内容即文案；时长探测已被打桩。

    内容寻址后文件名不再恰为 `{id}.mp3`（见 pipeline._content_addressed_audio），
    「哪段挂了谁的音」改由文件内容直接证明——比文件名更强：文件名对而内容错
    （覆盖/串音）也能被抓住。
    """

    def synthesize(self, text: str, voice: str | None, out_path: Path) -> Path:
        if text.strip() == "":  # 真引擎对空文案会失败（ffprobe check=True）：替身必须一样
            raise RuntimeError("TTS 空文案：槽位未被语言层填充")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(text.encode("utf-8"))
        return out_path


class _BrokenTts:
    def synthesize(self, text: str, voice: str | None, out_path: Path) -> Path:
        raise RuntimeError("云端不可达")


def _scenes() -> list[ConflictScore]:
    return [
        ConflictScore(scene_index=index, start=index * 12.0, end=index * 12.0 + 10.0, score=score)
        for index, score in enumerate([60, 85, 45, 90, 55, 75, 40, 95, 50, 65])
    ]


def _full_plan(episode_id: str, tts_dir: Path) -> PlanData:
    """真实 full_narration 编排（build_full 产出的全 ducked 时间轴）+ 旁白回填。"""
    plan = build_full(stamp([(1, episode_id, _scenes())]), StrategySpec())
    # 编剧层产出（见 test_narration_no_downgrade 对空文案的守卫）
    plan = plan.model_copy(update={
        "narration_texts": [
            t.model_copy(update={"text": f"第 {i} 段解说文案"})
            for i, t in enumerate(plan.narration_texts)
        ]
    })
    # 源长与 `_render` 种的 episodes.duration 同值（120s）：这里的 plan 后面真的会进渲染，
    # 两处不一致就是在测一个生产里不存在的形状。
    return pipeline.synthesize_narration_texts(
        plan, {"tts.engine": "edge"}, tts_dir, source_durations={episode_id: 120.0}
    )


def _stub_tts(monkeypatch: pytest.MonkeyPatch, engine: Any) -> None:
    monkeypatch.setattr(pipeline, "create_tts", lambda *a, **k: engine)
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", lambda _p: _TTS_DURATION_S)


def _render(
    monkeypatch: pytest.MonkeyPatch,
    conn: sqlite3.Connection,
    tmp_path: Path,
    builder: Callable[[str, Path], PlanData],
    settings: dict[str, str] | None = None,
) -> tuple[PlanData, list[list[str]], list[Any]]:
    """种真实项目/集/编排/导出记录，走 render_export，返回 plan_data、逐段 ffmpeg 命令
    与 Phase C 收到的响度目标。"""
    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    project_id = str(projects_repo.create(conn, "全片解说剧", str(tmp_path))["id"])
    episodes_repo.replace_all(
        conn,
        project_id,
        [{"episode_number": 1, "source_path": str(source), "duration": 120.0}],
    )
    episode_id = str(episodes_repo.list_by_project(conn, project_id)[0]["id"])
    plan = builder(episode_id, tmp_path / "cache" / "tts")

    plans_repo.create(conn, project_id, plan.mode, [episode_id], plan.model_dump())
    plan_id = str(plans_repo.list_by_project(conn, project_id)[0]["id"])
    plan_row = plans_repo.get(conn, plan_id)
    assert plan_row is not None
    # 与 export.start 一致的取数路径：plan_data 经库内 JSON 往返后才是导出看到的样子
    plan_data = PlanData.model_validate(plan_row["plan_data"])
    export_id = exports_repo.create(conn, project_id, plan_id, plan.mode)

    commands: list[list[str]] = []
    loudness_targets: list[Any] = []
    monkeypatch.setattr(encoder, "_run_cut", lambda args, *_a, **_k: commands.append(args))
    monkeypatch.setattr(encoder, "_concat", lambda _files, _out: None)
    # Phase C 不真跑 ffmpeg，但记录它收到的目标值——接线证明靠这份记录
    monkeypatch.setattr(
        encoder.loudness,
        "normalize_in_place",
        lambda _path, **kw: loudness_targets.append(kw["target"]),
    )
    merged_settings = dict(settings or {})
    merged_settings.setdefault("export.encoder", "libx264")  # 探针命令不进断言集
    context = SimpleNamespace(
        conn=conn,
        data_dir=tmp_path,
        work_dir=tmp_path / "cache",
        settings=merged_settings,
    )
    export_api.render_export(
        context,  # type: ignore[arg-type]
        export_api.ExportRun(
            export_id=export_id,
            project_id=project_id,
            plan_row=plan_row,
            plan_data=plan_data,
            cancel_event=threading.Event(),
        ),
        report=lambda _p, _m: None,
    )
    return plan_data, list(commands), loudness_targets


def _second_input(args: list[str]) -> str:
    """第二条 -i 的取值（第一条恒为源视频，第二条即该段旁白音频）。"""
    inputs = [args[i + 1] for i, arg in enumerate(args) if arg == "-i"]
    assert len(inputs) == 2, f"期望两路输入（源 + 旁白），实得 {inputs}"
    return inputs[1]


def test_full_narration_every_segment_mixes_its_own_narration(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """核心可达性证明：全 ducked 的 full_narration，每段命令都要有混音分支和自己的旁白。"""
    _stub_tts(monkeypatch, _StubTts())
    plan_data, commands, _targets = _render(monkeypatch, memory_db, tmp_path, _full_plan)

    assert plan_data.mode == "full_narration"
    assert len(commands) == len(plan_data.timeline) > 1
    assert all(segment.audio == "ducked" for segment in plan_data.timeline)
    # Phase A 是线程池并行，commands 是完成序 —— 按产物名 seg_NNN 归位再断言
    by_index = {int(Path(cmd[-1]).stem.split("_")[1]): cmd for cmd in commands}
    assert set(by_index) == set(range(len(plan_data.timeline)))
    for index, segment in enumerate(plan_data.timeline):
        cmd = by_index[index]
        joined = " ".join(cmd)
        assert segment.narration_id, f"第 {index} 段未回填 narration_id"
        assert "-filter_complex" in cmd, (
            f"第 {index} 段（{segment.audio}）没走混音分支 —— 旁白会整条丢失"
        )
        assert "amix=inputs=2" in joined
        assert "volume=0.08" in joined, "ducked 段原声应压到 8% 衬底（0d761d3 加深避让）"
        assert segment.subtitle_text, "解说字幕未回填 → 成片有音无字"
        tts_input = _second_input(cmd)
        # 内容寻址后文件名是 `{id}-{hash}.mp3`：id 前缀仍在，但「取对音」的铁证是内容——
        # 该段混进去的音频必须恰好装着该段解说字幕的文案（按 narration_id 配对，不按位置）。
        assert Path(tts_input).name.startswith(f"{segment.narration_id}-"), (
            f"第 {index} 段挂到了 {Path(tts_input).name} —— 旁白取音没按 narration_id 走"
        )
        assert Path(tts_input).read_text(encoding="utf-8") == segment.subtitle_text, (
            f"第 {index} 段的旁白音频装着别人的文案 —— 段↔音按位置错位或被覆盖"
        )
    # 每段只多挂一路输入（旁白），且各段互不相同
    assert len({_second_input(cmd) for cmd in commands}) == len(commands)


def test_full_narration_map_covers_every_index(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """映射层：ducked 时间轴的每个下标都要有条音，一个都不能漏。"""
    _stub_tts(monkeypatch, _StubTts())
    plan_data, _commands, _targets = _render(monkeypatch, memory_db, tmp_path, _full_plan)

    mapping = export_api.tts_audio_by_segment(plan_data)
    assert set(mapping) == set(range(len(plan_data.timeline)))
    texts_by_id = {text.id: text for text in plan_data.narration_texts}
    for index, segment in enumerate(plan_data.timeline):
        # 映射必须等于「按 narration_id 查文案表」拿到的那条 audio_path（绝不按位置），
        # 且文件内容就是该段字幕的文案——两条合起来才是「id 取音」的完整证明。
        assert mapping[index] == texts_by_id[str(segment.narration_id)].audio_path
        assert Path(mapping[index]).read_text(encoding="utf-8") == segment.subtitle_text


def test_failed_tts_fails_the_plan(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """配音失败 = 方案失败：不再有"回退原声继续渲染"这条路。"""
    _stub_tts(monkeypatch, _BrokenTts())
    with pytest.raises(RuntimeError, match="合成失败"):
        _render(monkeypatch, memory_db, tmp_path, _full_plan)


def test_render_export_feeds_settings_loudness_target_to_phase_c(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """生产接线证明：render_export 必须把 settings 里的响度目标传进 normalize_in_place。

    漏传（loudness_target 默认 None）等于 Phase C 在生产路径上根本没跑，
    成片响度回到没人负责的状态——这条用例就是那个"没跑"的探测器。
    """
    _stub_tts(monkeypatch, _StubTts())
    _, _, targets = _render(
        monkeypatch,
        memory_db,
        tmp_path,
        _full_plan,
        settings={"export.loudness_target_lufs": "-12"},
    )
    assert len(targets) == 1, "Phase C 必须被调用恰好一次"
    assert targets[0].integrated_lufs == -12.0, "目标必须来自 settings，而不是写死值"
    assert targets[0].true_peak_dbtp == -1.5, "settings 未给的键应回退 DEFAULTS"
