"""真机模式门禁压底判据（立案④声学道）的预测模型：段级天花板必须算进去。

2026-10-24 真机跑 indextts2 的 `full_narration`，这条判据报 −4.62 dB 超容差红，但压底是
照声明做事的：段级 `alimiter` 先把出厂就热的干音整体削掉 3.2–3.6 dB，而旧预测拿的是**没
过限幅**的干音响度。本文件把「引擎电平比天花板响」这一档钉成 CI 用例——门禁不许在换响引擎
时假红，也不许为了绿灯放宽容差。

变异锚点：把预测改回 `power_sum_db(dry_lufs, bed_lufs + bed_gain)`（漏掉限幅级），
`test_hot_dry_audio_passes_the_duck_gate` 必红；把探针滤镜手抄成字面量，
`test_limiter_probe_reuses_production_filter_builders` 必红；让探针量不到时悄悄退回旧模型，
`test_unmeasured_limiter_probe_is_a_failure_not_a_fallback` 必红。
"""

from __future__ import annotations

import importlib.util
import math
import random
import subprocess  # noqa: S404 - 参数为受控列表
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parents[3]
_GATE_SCRIPT = _REPO / "scripts" / "verify_modes.py"


def _load_mode_gate():
    spec = importlib.util.spec_from_file_location("verify_modes", _GATE_SCRIPT)
    assert spec is not None and spec.loader is not None
    gate = importlib.util.module_from_spec(spec)
    sys.modules["verify_modes"] = gate
    # verify_modes 在 import 时永久替换 encoder.cut_segment_args 为捕获包装，
    # exec 后必须还原——否则同进程后续测试内省该签名看到的是 (*args, **kw)
    # （test_drama_name_layer 会假红；同款还原见 test_w1_gates._load_mode_gate）。
    from dramaclip.engines.exporter import encoder

    original = encoder.cut_segment_args
    try:
        spec.loader.exec_module(gate)
    finally:
        encoder.cut_segment_args = original
    return gate


def _bed_gain_db(declared: str) -> float:
    return 20.0 * math.log10(float(declared))


def test_prediction_subtracts_the_measured_limiter_cut() -> None:
    """预测值 = 「过完段级天花板的干音」+「按声明压底的原声」，两者功率相加。

    四个数是 2026-10-24 真机 `full_narration` 第 0 段（58.04–67.70s）逐环节量的：
    干音 −13.6 LUFS / 真峰 +0.70 dBTP，同一条生产天花板滤镜把它削到 −17.2（cut −3.60），
    源窗 −12.4 LUFS，声明压底 volume=0.1；成片实测 −17.2 LUFS。
    """
    gate = _load_mode_gate()
    dry, cut, bed = -13.6, -3.60, -12.4
    gain = _bed_gain_db("0.1")
    measured = -17.2

    assert gate._expected_mixed_lufs(dry, cut, bed, gain) == pytest.approx(-17.07, abs=0.01)
    assert gate._expected_mixed_lufs(dry, 0.0, bed, gain) == pytest.approx(-13.54, abs=0.01)

    # 补上限幅级 → 残差 −0.13 dB 过门；漏算 → −3.66 dB（那轮报的最差段 −4.62，同一个形状）
    tol = gate.DUCK_RESIDUAL_TOL_DB
    assert abs(measured - gate._expected_mixed_lufs(dry, cut, bed, gain)) <= tol
    assert abs(measured - gate._expected_mixed_lufs(dry, 0.0, bed, gain)) > tol


def test_limiter_probe_reuses_production_filter_builders() -> None:
    """探针那一遍必须逐字复用生产构造（格式统一 + 真峰天花板），不许在门禁里抄第二份。

    抄来的数只能证明门禁跟自己一致，证明不了它量的是生产那条链——而 `alimiter` 的参数
    （limit / level=disabled / latency=true）任何一个不同都会削出不同的量。两条断言各管一头：
    相等式管"值现在对不对"，字面量缺席管"值是从哪来的"。
    """
    from dramaclip.engines.exporter import encoder

    gate = _load_mode_gate()
    assert gate._limiter_probe_filters() == (
        f"{encoder._audio_format_filter()},{encoder._peak_ceiling_filter()}"
    )
    assert "alimiter=limit=" not in _GATE_SCRIPT.read_text(encoding="utf-8"), (
        "门禁脚本里出现了手抄的天花板滤镜"
    )


def _record(tmp_path: Path, **kw: Any) -> dict[str, Any]:
    """一条混音段的插桩记录：三个文件都要真的存在（`_check_ducking` 认「文件在不在」）。"""
    base: dict[str, Any] = {
        "audio": "narration",
        "has_tts_input": True,
        "mixed": True,
        "filter_complex": f"volume={_NARRATION_BED}",
        "out_path": str(tmp_path / "seg.mp4"),
        "tts_path": str(tmp_path / "dry.wav"),
        "source": str(tmp_path / "ep1.mp4"),
        "start": 0.0,
        "end": 6.0,
    }
    base.update(kw)
    for key in ("out_path", "tts_path", "source"):
        Path(str(base[key])).write_bytes(b"x")
    return base


def _patch_readings(
    monkeypatch: pytest.MonkeyPatch, gate, readings: dict[str, tuple[float | None, float | None]],
    probe: tuple[float | None, float | None], bed_lufs: float | None,
) -> list[str]:
    """把三处响度量法换成假读数，并记下探针遍收到的滤镜串（真不真复用生产构造由上一条用例管）。"""
    seen: list[str] = []

    def fake_ebur128(path: Path, pre_filters: str = "") -> tuple[float | None, float | None]:
        if pre_filters:
            seen.append(pre_filters)
            return probe
        return readings[str(path)]

    monkeypatch.setattr(gate, "ebur128", fake_ebur128)
    monkeypatch.setattr(gate, "source_window_lufs", lambda *a: bed_lufs)
    return seen


_NARRATION_BED = "0.1"


def test_unmeasured_limiter_probe_is_a_failure_not_a_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """探针量不到 = 判红，不许退回「没过限幅的干音」那套旧算式。

    退回旧模型就是把这次的真红写成"环境没量到"蒙过去——业主立案④要的恰恰是这一列可信。
    """
    gate = _load_mode_gate()
    seg, dry = tmp_path / "seg.mp4", tmp_path / "dry.wav"
    readings = {str(seg): (-17.2, -8.1), str(dry): (-13.6, 0.7)}
    seen = _patch_readings(monkeypatch, gate, readings, (None, None), -12.4)

    failures, stats = gate._check_ducking("full_narration", [_record(tmp_path)])

    assert seen, "压底判据没跑限幅探针遍"
    assert "压底残差" not in "".join(failures)
    assert any("限幅" in f for f in failures), failures
    assert stats["duck_measured"] == 0


def test_measured_limiter_cut_lands_in_the_stats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """削底量要上账：残差归零之后，「引擎出厂电平变响」这件事只剩这一列看得见。

    #36（indextts2 干音超 0 dBFS）不能被这次修法藏起来，所以每一段的削底幅度进
    summary.json，并由基线漂移跟踪。
    """
    gate = _load_mode_gate()
    seg, dry = tmp_path / "seg.mp4", tmp_path / "dry.wav"
    readings = {str(seg): (-17.2, -8.1), str(dry): (-13.6, 0.7)}
    _patch_readings(monkeypatch, gate, readings, (-17.2, -7.9), -12.4)

    failures, stats = gate._check_ducking("full_narration", [_record(tmp_path)])

    assert failures == [], failures
    assert stats["duck_residuals"] == [pytest.approx(-0.13, abs=0.01)]
    assert stats["duck_limiter_cuts"] == [pytest.approx(-3.6, abs=0.02)]
    assert stats["duck_worst_limiter_db"] == pytest.approx(-3.6, abs=0.02)
    # 只落 summary.json 还不够：残差修好后它恒等于零，「引擎出厂电平变响」只剩这一列能报漂移
    assert "duck_worst_limiter_db" in gate._BASELINE_FLOAT_METRICS


def _ffmpeg() -> str:
    from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg

    return resolve_ffmpeg()


def _sh(args: list[str]) -> None:
    proc = subprocess.run(  # noqa: S603
        args, capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-800:]


@pytest.fixture(scope="module")
def hot_voice_over_bed(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """一条**真的会吃到段级限幅**的段：热干音（真峰 ≈0 dBFS）+ 已压底的原声源。

    干音用四个正弦相加（与 `test_mix` 的确定性原声床同法）而不是单支正弦：单支正弦的
    峰均比只有 3 dB，量不出"响引擎"的真实形状；四支叠加峰均比 ≈6 dB，落进 indextts2
    干音那一档（实测 LUFS −13.6 / 真峰 +0.7）。夹具自己先量一遍，干音没过 −2.5 dB 削底
    就直接红——素材悄悄变均匀的话，下面那条用例就成了量空气。
    """
    d = tmp_path_factory.mktemp("duck-limiter")
    src = d / "ep1.mp4"
    dry = d / "dry.wav"
    _sh([_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=8",
         "-f", "lavfi", "-i",
         "aevalsrc=0.30*sin(2*PI*97*t)+0.26*sin(2*PI*613*t)"
         "+0.22*sin(2*PI*2371*t)+0.18*sin(2*PI*5903*t)"
         "|0.30*sin(2*PI*101*t)+0.26*sin(2*PI*617*t)"
         "+0.22*sin(2*PI*2377*t)+0.18*sin(2*PI*5909*t):s=48000:d=8",
         "-map", "0:v", "-map", "1:a",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
         "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-shortest", str(src)])
    # 旁白形态照真机：mono 24 kHz（`test_mix` 的 `stereo_source_and_mono_tts` 同法）
    _sh([_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i",
         "aevalsrc=0.34*sin(2*PI*113*t)+0.30*sin(2*PI*701*t)"
         "+0.22*sin(2*PI*1801*t)+0.14*sin(2*PI*4201*t):s=24000:d=6",
         "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(dry)])
    return src, dry


def test_hot_dry_audio_passes_the_duck_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hot_voice_over_bed: tuple[Path, Path]
) -> None:
    """真渲染 + 真量法：引擎再响也不许让压底判据假红（这条在旧模型下必红）。

    用生产 `cut_segment_args` 出段、用门禁自己的三条量法读数，所以它测的是判据模型本身，
    不是某个假想的滤镜串。
    """
    from dramaclip.engines.exporter import encoder

    gate = _load_mode_gate()
    monkeypatch.setattr(gate, "FFMPEG", _ffmpeg())
    src, dry = hot_voice_over_bed
    out = tmp_path / "seg.mp4"

    gate.CAPTURED.clear()
    args = gate._capturing_cut_args(
        str(src), str(out), start=0.5, end=6.0, audio="narration",
        tts_audio=str(dry), rng=random.Random(0),
    )
    record = gate.CAPTURED[-1]
    _sh([_ffmpeg(), *args])

    dry_lufs, dry_peak = gate.ebur128(dry)
    limited_lufs, _ = gate.ebur128(dry, pre_filters=gate._limiter_probe_filters())
    assert dry_lufs is not None and limited_lufs is not None
    assert limited_lufs - dry_lufs < -2.5, (
        f"这段干音只被天花板削掉 {limited_lufs - dry_lufs:.2f} dB，没进「响引擎」区间，"
        f"用例在量空气（干音 {dry_lufs} LUFS / 真峰 {dry_peak} dBTP）"
    )

    failures, stats = gate._check_ducking("full_narration", [record])
    assert failures == [], failures
    assert stats["duck_measured"] == 1
    assert abs(stats["duck_max_residual_db"]) <= gate.DUCK_RESIDUAL_TOL_DB

    # 旧模型（干音不过限幅）在同一段上会给出多大残差：把它算出来，证明这条用例真的
    # 覆盖了 2026-10-24 那形状，而不是恰好两段都绿
    voiced, _ = gate.ebur128(out)
    bed = gate.source_window_lufs(src, 0.5, 6.0)
    old_predicted = gate.power_sum_db(dry_lufs, bed + _bed_gain_db(encoder._NARRATION_BED_VOLUME))
    assert voiced - old_predicted < -gate.DUCK_RESIDUAL_TOL_DB, (
        f"旧模型残差只有 {voiced - old_predicted:.2f} dB，本用例拦不住漏算限幅级的回归"
    )
