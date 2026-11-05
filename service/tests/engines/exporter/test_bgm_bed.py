"""BGM 床混音（C 项接线 → 批3 听感治理）：真 ffmpeg 小样本，验证铺床不变量。

床是增强项：混音失败必须向上抛（由 _export_plan_once 的 catch 兜成「无 BGM 出片」
），本文件同时钉住这条失败路径。批3 起额外钉三件事：床响度归一（响轻两曲落床
同响）、循环 crossfade（短曲接长不改成片时长）、PCM 中间件（少一代 AAC 的链形状）。
"""

from __future__ import annotations

import math
import re
import subprocess
import sys
import wave
from pathlib import Path

import pytest

from dramaclip.engines.exporter import encoder
from dramaclip.infra.ffmpeg import probe as probe_mod
from dramaclip.infra.ffmpeg import runner
from dramaclip.infra.ffmpeg.binaries import resolve_ffprobe

_RATE = 16000


def _write_tone_wav(path: Path, seconds: float, amp: int) -> Path:
    """单频正弦 wav（床与成片用不同振幅，混音前后能量可区分）。"""
    frames = b"".join(
        int.to_bytes(int(amp * math.sin(2 * math.pi * 440 * k / _RATE)), 2, "little", signed=True)
        for k in range(int(_RATE * seconds))
    )
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_RATE)
        wf.writeframes(frames)
    return path


def _as_film(wav: Path, out: Path, *, seconds: float = 1.0) -> Path:
    """wav → 成片形状（视频流+音轨的 mp4）：真实成片恒有视频流，_map 0:v 依赖它。"""
    runner.run(
        ["-y", "-f", "lavfi", "-i", f"color=c=black:s=320x240:d={seconds:.3f}",
         "-i", str(wav), "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
         "-c:a", "aac", str(out)],
        timeout_s=120,
    )
    return out


def _mean_volume(path: Path) -> float:
    null_dev = "NUL" if sys.platform == "win32" else "/dev/null"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        [str(runner.resolve_ffmpeg()), "-i", str(path), "-af", "volumedetect",
         "-f", "null", null_dev],
        capture_output=True, text=True, timeout=60, creationflags=flags, check=False,
    )
    match = re.search(r"mean_volume:\s*(-?[\d.]+)\s*dB", result.stderr)
    assert match, result.stderr[-400:]
    return float(match.group(1))


def test_bgm_bed_mixes_bed_over_film_and_keeps_duration(tmp_path: Path) -> None:
    """循环补齐＋尾淡出＋躲床＋amix：成片时长不变，能量因叠床显著升高。"""
    film = _as_film(_write_tone_wav(tmp_path / "film.wav", 1.0, 200), tmp_path / "film.mp4")
    bed = _write_tone_wav(tmp_path / "bed.wav", 3.0, 16000)
    before = _mean_volume(film)

    mixed = encoder._mix_bgm_bed(film, bed, tmp_path / "work")

    media = probe_mod.probe(mixed)
    assert media.duration_s == pytest.approx(1.0, abs=0.3), "循环补齐不改变成片时长"
    after = _mean_volume(mixed)
    assert after > before + 5.0, f"叠床后能量应显著升高（{before:.1f} → {after:.1f}）"


def test_bgm_bed_loudness_equalizes_tracks(tmp_path: Path) -> None:
    """床响度归一：响/轻两曲（20 dB 之差）落床后成片能量应同响（±1.5 dB）。

    固定 0.15 线性增益时代这一差值原样透进成片（换曲=换片感）；批3 起按
    曲目实测 LUFS 算增益，任何曲目落床同响（真机合成信号实测 0.00 dB 差）。
    """
    film = _as_film(_write_tone_wav(tmp_path / "film.wav", 1.0, 60), tmp_path / "film.mp4")
    loud = _write_tone_wav(tmp_path / "loud.wav", 3.0, 20000)
    quiet = _write_tone_wav(tmp_path / "quiet.wav", 3.0, 2000)

    m_loud = encoder._mix_bgm_bed(film, loud, tmp_path / "w1")
    m_quiet = encoder._mix_bgm_bed(film, quiet, tmp_path / "w2")

    diff = abs(_mean_volume(m_loud) - _mean_volume(m_quiet))
    assert diff <= 1.5, f"响轻两曲落床差 {diff:.2f} dB：床响度归一没生效"


def test_bgm_bed_short_track_loops_without_duration_change(tmp_path: Path) -> None:
    """短曲 crossfade 接长：1.2s 曲 × 4s 片走多副本链，时长不变（无咔哒的结构前提）。"""
    film = _as_film(
        _write_tone_wav(tmp_path / "film.wav", 4.0, 100), tmp_path / "film.mp4", seconds=4.0
    )
    bed = _write_tone_wav(tmp_path / "bed.wav", 1.2, 16000)

    mixed = encoder._mix_bgm_bed(film, bed, tmp_path / "work")

    assert probe_mod.probe(mixed).duration_s == pytest.approx(4.0, abs=0.3)


def test_bgm_bed_lossless_intermediate(tmp_path: Path) -> None:
    """PCM 中间件：lossless_intermediate=True 产出 .mov + PCM——供响度归一同链
    续编，开 BGM 成片少一代 AAC 有损（段 128k → 终编共两代）。"""
    film = _as_film(_write_tone_wav(tmp_path / "film.wav", 1.0, 200), tmp_path / "film.mp4")
    bed = _write_tone_wav(tmp_path / "bed.wav", 3.0, 16000)

    mixed = encoder._mix_bgm_bed(film, bed, tmp_path / "work", lossless_intermediate=True)

    assert mixed.suffix == ".mov"
    codec = subprocess.run(
        [resolve_ffprobe(), "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=codec_name", "-of", "csv=p=0", str(mixed)],
        capture_output=True, text=True, timeout=60, check=False,
    ).stdout.strip()
    assert codec == "pcm_s16le", f"中间件应为 PCM（实测 {codec}）——否则白省不出一代"


def test_bgm_bed_raises_on_broken_track(tmp_path: Path) -> None:
    """坏曲目（文本冒充音频）：_mix_bgm_bed 如实抛——吞掉是 _export_plan_once 的职责。"""
    film = _as_film(_write_tone_wav(tmp_path / "film.wav", 1.0, 8000), tmp_path / "film.mp4")
    broken = tmp_path / "bed.mp3"
    broken.write_text("这不是音频", encoding="utf-8")
    with pytest.raises(Exception):  # noqa: B017 - ffmpeg 对坏输入的异常类型不承诺
        encoder._mix_bgm_bed(film, broken, tmp_path / "work")
