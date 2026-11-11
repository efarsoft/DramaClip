"""干音电平契约：配音进混音链前量进参考带、带外纯增益拉回，峰值仍归段级限幅。

五条判据（实测账与设计规格 §9 同处一份）：带外才动字节；抬升有峰值闸、衰减无闸；
先验后搬（复测位移不过就不搬）；量不到不静默；无损 WAV 不随手转有损。
"""

from __future__ import annotations

import math
import subprocess
import wave
from pathlib import Path

import pytest

from dramaclip.engines.exporter import loudness
from dramaclip.engines.tts import level_fix
from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg

_FFMPEG = resolve_ffmpeg()


def _render_tone(out: Path, gain_db: float, *, duration: float = 3.0) -> None:
    """真渲一段正弦干音（22050 Hz 单声道 16bit，与本地引擎出厂同格式）。"""
    subprocess.run(  # noqa: S603
        [
            _FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=22050:duration={duration}",
            "-af", f"volume={gain_db}dB", "-ar", "22050", "-ac", "1", "-c:a", "pcm_s16le",
            str(out),
        ],
        check=True,
    )


def _render_dry(out: Path, lufs: float) -> tuple[float, float]:
    """渲一段**集成响度已知**的干音：先量 0 dB 参考，再按差值加纯增益。

    不写死 `volume=` 的数字——lavfi `sine` 的出厂峰值随版本漂，跟着写死就是下一次
    「素材到底带外没有」的假红。
    """
    _render_tone(out, 0.0)
    base_lufs, _ = _gate_reading(out)
    _render_tone(out, lufs - base_lufs)
    return _gate_reading(out)


def _render_sparse(out: Path, *, level: int = 32700) -> None:
    """3% 占空比的稀疏正弦：频峰比大到抬升闸会咬住——纯策略测不到的形状才值得渲。

    用 `wave` 直接写而不是找 ffmpeg 滤镜：占空比和幅度都要精确，闸判的是
    「响度在带下、真峰顶在哪」，素材含糊不得。
    """
    total = 22050 * 2
    frames = bytearray()
    for index in range(total):
        value = (
            level * math.sin(2.0 * math.pi * 440.0 * index / 22050.0)
            if (index % 2000) < 60
            else 0.0
        )
        frames += int(value).to_bytes(2, "little", signed=True)
    with wave.open(str(out), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(22050)
        handle.writeframes(bytes(frames))


def _gate_reading(path: Path) -> tuple[float, float]:
    """用门禁那把尺子量（与 `measure_dry_level` 逐字同一条命令）。"""
    proc = subprocess.run(  # noqa: S603
        [_FFMPEG, *loudness.measure_gate_args(str(path))],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    measurement = loudness.parse_gate_reading(proc.stderr)
    return measurement.integrated_lufs, measurement.true_peak_dbtp


def _clamp_branch(before_lufs: float, before_dbtp: float) -> tuple[float, float]:
    """把 `plan_dry_gain` 的钳位条件摊开，供用例先验素材落没落在这一支上。"""
    return (
        level_fix.DRY_LEVEL_TARGET_LUFS - before_lufs,
        level_fix.DRY_LEVEL_HEADROOM_DBTP - before_dbtp,
    )


# ---- 纯策略：`plan_dry_gain` 不碰磁盘，把闸的四种落点一次说清 ----------------


def test_in_band_dry_gets_no_gain() -> None:
    assert level_fix.plan_dry_gain(level_fix.DRY_LEVEL_TARGET_LUFS - 0.9, -20.0) == (
        0.0,
        "",
    )


def test_quiet_dry_is_lifted_exactly_to_the_reference() -> None:
    gain, note = level_fix.plan_dry_gain(-30.0, -38.0)
    assert gain == pytest.approx(17.0)
    assert note == ""


def test_loud_dry_is_brought_down_without_a_gate() -> None:
    """衰减不设闸：已经比参考响的干音该拉回来，哪怕它真峰正顶着天花板往下掉。"""
    gain, note = level_fix.plan_dry_gain(-8.0, -0.5)
    assert gain == pytest.approx(-5.0)
    assert note == ""


def test_lift_is_clamped_to_the_peak_gate() -> None:
    """抬到一半就顶闸：只施能够到闸的量，差额写进回执，不许自己扩闸。"""
    gain, note = level_fix.plan_dry_gain(-20.0, -5.0)
    assert gain == pytest.approx(level_fix.DRY_LEVEL_HEADROOM_DBTP - -5.0)
    assert "钳住" in note and "需要" in note, note


def test_dry_already_past_the_gate_is_never_lifted() -> None:
    """真峰已过闸的干音抬不动——硬抬就是把削顶烘进波形，宁可在带外留痕。"""
    gain, note = level_fix.plan_dry_gain(-30.0, -0.5)
    assert gain == 0.0
    assert "抬升闸" in note and "未改写" in note, note


def test_gain_below_the_floor_is_not_a_re_encode() -> None:
    """闸缝只剩零点几 dB 时不值得多付一次有损重编码——判据是「听不听得出来」。"""
    gain, note = level_fix.plan_dry_gain(-30.0, level_fix.DRY_LEVEL_HEADROOM_DBTP - 0.01)
    assert gain == 0.0
    assert "抬升闸" in note, note


def test_reference_numbers_stay_internally_consistent() -> None:
    """参考值来自实测，但**推导关系**要钉住：闸必须在 0 dBFS 之下（重采样与下游编码
    自己会长出采样间过冲），复测判据从带宽推导——不留第二个数。
    """
    assert level_fix.DRY_LEVEL_HEADROOM_DBTP < 0.0
    assert 0.0 < level_fix.DRY_LEVEL_TOLERANCE_DB < 2.0
    assert (
        pytest.approx(level_fix.DRY_LEVEL_TOLERANCE_DB * 2.0)
        == level_fix._RECHECK_TOLERANCE_DB  # noqa: SLF001 - 钉的是推导关系，不是数值
    )


# ---- 真渲染：契约确实把干音带进了带，且没有顺手换编码器 ----------------


def test_quiet_dry_is_lifted_into_the_band(tmp_path: Path) -> None:
    dry = tmp_path / "quiet.wav"
    before_lufs, before_tp = _render_dry(dry, -28.0)
    assert before_lufs < level_fix.DRY_LEVEL_TARGET_LUFS - level_fix.DRY_LEVEL_TOLERANCE_DB

    report = level_fix.normalize_dry_level(dry)
    after_lufs, after_tp = _gate_reading(dry)

    assert report.measured is True and report.applied_gain_db > 0.0
    assert abs(after_lufs - level_fix.DRY_LEVEL_TARGET_LUFS) <= level_fix.DRY_LEVEL_TOLERANCE_DB
    # 抬升闸的意义就在这行：抬完的真峰仍然离满量程有余量
    assert after_tp <= level_fix.DRY_LEVEL_HEADROOM_DBTP + 0.2, after_tp
    assert after_tp - before_tp == pytest.approx(report.applied_gain_db, abs=0.2)
    assert [p.name for p in tmp_path.glob("*.level*")] == []


def test_loud_dry_is_brought_down_to_the_reference(tmp_path: Path) -> None:
    dry = tmp_path / "loud.wav"
    before_lufs, _ = _render_dry(dry, -6.0)
    assert before_lufs > level_fix.DRY_LEVEL_TARGET_LUFS + level_fix.DRY_LEVEL_TOLERANCE_DB

    report = level_fix.normalize_dry_level(dry)
    after_lufs, _ = _gate_reading(dry)

    assert report.applied_gain_db < 0.0
    assert after_lufs == pytest.approx(level_fix.DRY_LEVEL_TARGET_LUFS, abs=0.5)
    # 纯增益是精确位移：回执上的增益数必须和两处读数之差对得上
    assert before_lufs - after_lufs == pytest.approx(-report.applied_gain_db, abs=0.2)


def test_dry_inside_the_band_is_left_byte_identical(tmp_path: Path) -> None:
    """带内一个字节都不许改写——一次「顺手归一」就是一场没人要求的重编码。"""
    dry = tmp_path / "inband.wav"
    before_lufs, _ = _render_dry(dry, level_fix.DRY_LEVEL_TARGET_LUFS)
    assert abs(before_lufs - level_fix.DRY_LEVEL_TARGET_LUFS) <= (
        level_fix.DRY_LEVEL_TOLERANCE_DB
    ), "素材没造在带内，用例测不到这条路径"
    original = dry.read_bytes()

    report = level_fix.normalize_dry_level(dry)

    assert report.applied_gain_db == 0.0
    assert "未改写" in report.log_line(), report.log_line()
    assert dry.read_bytes() == original


def test_clamped_lift_lands_and_survives_the_recheck(tmp_path: Path) -> None:
    """钳位抬升必须真的搬回去：复测若按「逼近参考」验收，这一支的产物每次都被扔掉。"""
    dry = tmp_path / "sparse.wav"
    _render_sparse(dry, level=16423)
    before_lufs, before_tp = _gate_reading(dry)
    wanted, ceiling = _clamp_branch(before_lufs, before_tp)
    assert wanted > level_fix.DRY_LEVEL_TOLERANCE_DB > 0, "素材没在带外，测不到抬升"
    assert (
        level_fix._MIN_APPLY_GAIN_DB < ceiling < wanted  # noqa: SLF001 - 落进钳位支才算数
    ), f"素材没落进钳位支：wanted={wanted:.2f} ceiling={ceiling:.2f}"
    original = dry.read_bytes()

    report = level_fix.normalize_dry_level(dry)
    after_lufs, after_tp = _gate_reading(dry)

    assert report.applied_gain_db == pytest.approx(ceiling, abs=0.1), report.note
    assert dry.read_bytes() != original, "钳位产物被复测判死了"
    assert after_lufs == pytest.approx(before_lufs + ceiling, abs=0.3)
    assert after_tp <= level_fix.DRY_LEVEL_HEADROOM_DBTP + 0.2, after_tp
    assert "钳住" in report.note, report.note
    assert list(tmp_path.glob("*.level*")) == []


def test_lifted_past_the_gate_stays_untouched_and_says_so(tmp_path: Path) -> None:
    """响度在带下、真峰顶在闸上——抬升闸必须真的咬住，产物不许落盘。"""
    dry = tmp_path / "spiky.wav"
    _render_sparse(dry)
    before_lufs, before_tp = _gate_reading(dry)
    assert before_lufs < level_fix.DRY_LEVEL_TARGET_LUFS - level_fix.DRY_LEVEL_TOLERANCE_DB
    assert before_tp > level_fix.DRY_LEVEL_HEADROOM_DBTP, "素材没顶到闸，用例测不到东西"
    original = dry.read_bytes()

    report = level_fix.normalize_dry_level(dry)

    assert report.applied_gain_db == 0.0, "抬升闸被绕过，把削顶烘进波形了"
    assert "抬升闸" in report.note, report.note
    assert dry.read_bytes() == original
    assert list(tmp_path.glob("*.level*")) == [], "抬不动却留下了暂存产物"


def test_wav_bytes_named_mp3_keep_their_container(tmp_path: Path) -> None:
    """干音文件名统一 `.mp3`，有的引擎写的却是 WAV 字节。

    契约跟着扩展名写暂存就会把一段无损 WAV 转成有损 mp3：这里改的是响度，
    不是顺手换编码器。判据只有一条——搬回原路径的字节仍是 RIFF。
    """
    real_wav = tmp_path / "loud.wav"
    _render_dry(real_wav, -6.0)
    dry = tmp_path / "dry.mp3"
    dry.write_bytes(real_wav.read_bytes())

    report = level_fix.normalize_dry_level(dry)

    assert report.measured is True and report.applied_gain_db != 0.0
    assert dry.read_bytes()[:4] == b"RIFF", "无损干音被契约转码成了有损 mp3"
    after_lufs, _ = _gate_reading(dry)
    assert abs(after_lufs - level_fix.DRY_LEVEL_TARGET_LUFS) <= level_fix.DRY_LEVEL_TOLERANCE_DB


def test_recheck_displacement_failure_keeps_the_original_dry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """先验后搬：产物复测的位移对不上计划增益就保留原干音，回执说清而不是报成已修好。"""
    dry = tmp_path / "loud.wav"
    _render_dry(dry, -6.0)
    original = dry.read_bytes()
    readings = iter([(-6.0, -9.0), (-30.0, -24.0)])
    monkeypatch.setattr(level_fix, "measure_dry_level", lambda path: next(readings))

    report = level_fix.normalize_dry_level(dry)

    assert report.applied_gain_db == 0.0, "复测没过的产物被搬进正式路径了"
    assert report.after_lufs == pytest.approx(-30.0), "复测读数被吞了，下次无从对账"
    assert "位移不符" in report.note and "保留原干音" in report.note, report.note
    assert dry.read_bytes() == original
    assert list(tmp_path.glob("*.level*")) == []


def test_gain_step_never_raises_out_of_the_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """增益步炸了（超时/占用/找不到 ffmpeg）也只能出一条回执——电平不配判死一段配音。"""
    dry = tmp_path / "loud.wav"
    _render_dry(dry, -6.0)
    original = dry.read_bytes()
    monkeypatch.setattr(level_fix, "measure_dry_level", lambda path: (-6.0, -9.0))
    monkeypatch.setattr(
        level_fix.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(cmd="ffmpeg", timeout=level_fix._TIMEOUT_S)  # noqa: SLF001
        ),
    )

    report = level_fix.normalize_dry_level(dry)

    assert report.measured is True and report.applied_gain_db == 0.0
    assert "TimeoutExpired" in report.note, report.note
    assert "未走完" in report.note, report.note
    assert dry.read_bytes() == original
    assert list(tmp_path.glob("*.level*")) == []


def test_unmeasurable_dry_is_reported_not_assumed_compliant(tmp_path: Path) -> None:
    """量不到 = 回执里明说量不到，不是「当它合规」跳过（零值空转是历史事故形状）。"""
    dry = tmp_path / "no_audio.mp4"
    subprocess.run(  # noqa: S603
        [_FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "color=c=black:s=32x32:d=1", "-an", str(dry)],
        check=True,
    )
    original = dry.read_bytes()

    report = level_fix.normalize_dry_level(dry)

    assert report.measured is False
    assert report.applied_gain_db == 0.0
    assert report.note, "量不到却说不清为什么"
    assert "未量到" in report.log_line(), report.log_line()
    assert dry.read_bytes() == original, "没量成就不该动文件"


def test_missing_dry_is_reported_not_raised(tmp_path: Path) -> None:
    report = level_fix.normalize_dry_level(tmp_path / "absent.mp3")
    assert report.measured is False and "不在" in report.note


def test_gain_is_applied_with_the_shared_volume_filter(tmp_path: Path) -> None:
    """施加增益的滤镜串必须显式带 dB，不能用裸数字（裸数字是线性倍率，语义不同）。"""
    args = level_fix.apply_gain_args(str(tmp_path / "a.wav"), str(tmp_path / "b.wav"), -3.5)
    joined = " ".join(args)
    assert "volume=-3.5000dB" in joined, joined
    value = args[args.index("-af") + 1].split("volume=")[1].split("dB")[0]
    assert math.isclose(float(value), -3.5)
    assert "-vn" in args, "纯音频契约不该带视频流"


def test_receipt_names_the_band_and_both_reads() -> None:
    """上屏那行要能单独读懂：动了就报前后响度与施加的增益，没动就说为什么没动。"""
    moved = level_fix.DryLevelReport("s1.mp3", True, -30.0, -38.0, -13.0, -16.0, 17.0, "note")
    assert "参考" in moved.log_line(), moved.log_line()
    assert "-30.00→-13.00" in moved.log_line(), moved.log_line()
    assert "+17.00" in moved.log_line(), moved.log_line()
    assert moved.log_line().endswith("；note"), moved.log_line()

    held = level_fix.DryLevelReport("s1.mp3", True, -30.0, -0.5, -30.0, -0.5, 0.0, "已到抬升闸")
    assert "未改写" in held.log_line(), held.log_line()
    assert "→" not in held.log_line(), held.log_line()
