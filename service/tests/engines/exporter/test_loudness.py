"""Phase C 响度归一：命令构建、测量解析、复核超差即抛。ffmpeg 在此不真跑。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from dramaclip.engines.exporter import encoder, loudness
from dramaclip.engines.narration.models import PlanData, StrategySpec, TimelineSegment

_TARGET = loudness.LoudnessTarget(integrated_lufs=-14.0, true_peak_dbtp=-1.5)

_STDERR = """
[Parsed_loudnorm @ 0x...] Input Integrated: -23.7 LUFS
{
	"input_i" : "-23.72",
	"input_tp" : "-3.15",
	"input_lra" : "8.40",
	"input_thresh" : "-34.10",
	"output_i" : "-14.02",
	"target_thresh" : "-24.50",
	"offset" : "0.50"
}
size=N/A time=00:01:30.00
"""


def test_measure_args_target_and_print_format() -> None:
    args = loudness.measure_args("in.mp4", _TARGET)
    joined = " ".join(args)
    assert "loudnorm=I=-14.0:TP=-1.5:LRA=11.0:print_format=json" in joined
    assert "-f null" in joined and "-map 0:a:0" in joined


def test_parse_measurements() -> None:
    m = loudness.parse_measurements(_STDERR)
    assert (m.integrated_lufs, m.true_peak_dbtp, m.lra) == (-23.72, -3.15, 8.40)
    assert m.threshold == -34.10 and m.target_threshold == -24.50
    assert m.offset_lu == 0.50, "两遍法的补偿量必须回喂，丢掉它等于二次偏移"


def test_parse_missing_block_raises() -> None:
    with pytest.raises(RuntimeError, match="未输出"):
        loudness.parse_measurements("nothing here")


def test_silent_audio_raises() -> None:
    with pytest.raises(RuntimeError, match="无声"):
        loudness.parse_measurements(
            '{"input_i": "-inf", "input_tp": "-inf", "input_lra": "0.0",'
            ' "input_thresh": "-inf", "target_thresh": "-inf"}'
        )


def test_normalize_args_copies_video_and_resamples() -> None:
    m = loudness.parse_measurements(_STDERR)
    args = loudness.normalize_args("in.mp4", "out.mp4", _TARGET, m)
    joined = " ".join(args)
    assert "-c:v copy" in joined, "视频流必须复制：重编码会让 Phase A 的消重参数白做"
    assert "measured_I=-23.72" in joined and "measured_TP=-3.15" in joined
    assert "offset=0.5" in joined, "第一遍自报的 offset 必须回喂"
    assert "linear=true" in joined
    assert "-ar" in args and "48000" in args, "loudnorm 内部 192k，必须落回 48k"
    assert "-map_metadata" in args and "-1" in args


def test_target_from_settings_reads_keys() -> None:
    target = loudness.LoudnessTarget.from_settings(
        {"export.loudness_target_lufs": "-12", "export.loudness_true_peak_dbtp": "-1.0"}
    )
    assert (target.integrated_lufs, target.true_peak_dbtp) == (-12.0, -1.0)


def test_target_from_settings_falls_back_to_defaults() -> None:
    """缺失与脏值都回退 DEFAULTS：出片不得因设置表里一格垃圾字符而停摆。"""
    assert loudness.LoudnessTarget.from_settings({}) == _TARGET
    garbage = loudness.LoudnessTarget.from_settings({"export.loudness_target_lufs": "abc"})
    assert garbage.integrated_lufs == -14.0 and garbage.true_peak_dbtp == -1.5


# ---- normalize_in_place 的守卫分支：每条都要"删掉即红"（本批次的规矩） ----


def _measure_stderr(integrated: float, true_peak: float) -> str:
    return (
        f'{{"input_i": "{integrated}", "input_tp": "{true_peak}", "input_lra": "8.0",'
        f' "input_thresh": "-30.0", "target_thresh": "-24.0", "offset": "0.5"}}'
    )


def _stub_run(
    monkeypatch: pytest.MonkeyPatch, measurements: list[str], *, produce_file: bool = True
) -> list[list[str]]:
    """替身 _run：测量遍按序吐 stderr，归一遍产出（或不产出）staged 文件。"""
    seen: list[list[str]] = []

    def fake_run(args: list[str]) -> str:
        seen.append(list(args))
        if "null" in args:  # 测量遍（-f null）
            index = len([item for item in seen if "null" in item]) - 1
            return measurements[index]
        if produce_file:  # 归一遍：写出 staged 产物
            Path(args[-1]).write_bytes(b"normalized")
        return ""

    monkeypatch.setattr(loudness, "_run", fake_run)
    return seen


def test_normalize_in_place_replaces_file_and_returns_recheck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """顺路径：staged 产物原地替换成片，返回的必须是归一后那次复核实测。"""
    film = tmp_path / "final.mp4"
    film.write_bytes(b"film")
    seen = _stub_run(
        monkeypatch,
        [_measure_stderr(-23.7, -3.1), _measure_stderr(-14.1, -2.0)],
    )
    checked = loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    assert checked.integrated_lufs == -14.1, "返回的必须是复核（第二遍）实测，不是归一前的"
    assert film.read_bytes() == b"normalized", "成片必须被归一产物原地替换"
    assert len(seen) == 3, "两遍测量 + 一遍归一，缺一不可"


def test_recheck_drift_beyond_tolerance_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """复核是 Phase C 的验收线：归一后仍偏离目标超容差必须抛，不得放行。"""
    film = tmp_path / "final.mp4"
    film.write_bytes(b"film")
    _stub_run(
        monkeypatch,
        [_measure_stderr(-23.7, -3.1), _measure_stderr(-20.0, -3.0)],  # 复核差 6 LU
    )
    with pytest.raises(loudness.LoudnessError, match="偏离目标"):
        loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")


def test_recheck_true_peak_over_limit_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    film = tmp_path / "final.mp4"
    film.write_bytes(b"film")
    _stub_run(
        monkeypatch,
        [_measure_stderr(-23.7, -3.1), _measure_stderr(-14.0, -0.4)],  # 真峰超 -1.5+0.5
    )
    with pytest.raises(loudness.LoudnessError, match="真峰值超标"):
        loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")


def test_normalize_without_output_file_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    film = tmp_path / "final.mp4"
    film.write_bytes(b"film")
    _stub_run(monkeypatch, [_measure_stderr(-23.7, -3.1)], produce_file=False)
    with pytest.raises(loudness.LoudnessError, match="未产出文件"):
        loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")


def test_parse_missing_field_raises() -> None:
    with pytest.raises(loudness.LoudnessError, match="缺字段"):
        loudness.parse_measurements('{"input_i": "-23.7"}')


def test_parse_garbage_number_raises() -> None:
    with pytest.raises(loudness.LoudnessError, match="无法解析"):
        loudness.parse_measurements(
            '{"input_i": "abc", "input_tp": "-3.0", "input_lra": "8.0",'
            ' "input_thresh": "-30.0"}'
        )


def test_run_raises_on_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loudness, "resolve_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(
        loudness.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "boom"),
    )
    with pytest.raises(loudness.LoudnessError, match="退出码 1"):
        loudness._run([])


# ---- Phase C 接线证明 ----


def _one_segment_plan(tmp_path: Path) -> tuple[PlanData, str]:
    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    plan = PlanData(
        mode="raw_clip",
        strategy=StrategySpec(),
        timeline=[TimelineSegment(episode_id="ep1", start=0.0, end=5.0)],
    )
    return plan, str(source)


def test_export_plan_runs_loudness_after_concat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase C 必须真被调用：它是成片响度的唯一负责人，漏调等于回到没人管响度的状态。"""
    plan, source = _one_segment_plan(tmp_path)
    out = tmp_path / "final.mp4"
    calls: list[str] = []
    monkeypatch.setattr(encoder, "_run_cut", lambda _args: None)
    monkeypatch.setattr(
        encoder, "_concat", lambda _files, target: Path(target).write_bytes(b"film")
    )
    monkeypatch.setattr(
        encoder.loudness,
        "normalize_in_place",
        lambda path, **_kw: calls.append(Path(path).name),
    )
    encoder.export_plan(
        plan,
        {"ep1": source},
        out,
        tmp_path / "work",
        loudness_target=loudness.LoudnessTarget(integrated_lufs=-14.0, true_peak_dbtp=-1.5),
    )
    assert calls == ["final.mp4"]


def test_export_plan_skips_loudness_when_target_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`loudness_target=None` 是显式关闭位（今天只有测试用它）——生产调用方必须传值。"""
    plan, source = _one_segment_plan(tmp_path)
    monkeypatch.setattr(encoder, "_run_cut", lambda _args: None)
    monkeypatch.setattr(
        encoder, "_concat", lambda _files, target: Path(target).write_bytes(b"film")
    )
    monkeypatch.setattr(
        encoder.loudness,
        "normalize_in_place",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("归一不该被调用")),
    )
    encoder.export_plan(plan, {"ep1": source}, tmp_path / "final.mp4", tmp_path / "work")
