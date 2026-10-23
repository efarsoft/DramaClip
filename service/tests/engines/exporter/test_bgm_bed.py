"""BGM 床混音（C 项接线）：真 ffmpeg 小样本，验证「铺了床、时长不变、坏了不吞」。

床是增强项：混音失败必须向上抛（由 _export_plan_once 的 catch 兜成「无 BGM 出片」
），本文件同时钉住这条失败路径。
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

_RATE = 16000


def _write_tone_wav(path: Path, seconds: float, amp: int) -> None:
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


def _as_film(wav: Path, out: Path) -> Path:
    """wav → 成片形状（视频流+音轨的 mp4）：真实成片恒有视频流，_map 0:v 依赖它。"""
    runner.run(
        ["-y", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=1.0",
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
    """循环补齐＋尾淡出＋amix：成片时长不变，能量因叠床显著升高。"""
    film = _as_film(_write_tone_wav(tmp_path / "film.wav", 1.0, 200), tmp_path / "film.mp4")
    bed = _write_tone_wav(tmp_path / "bed.wav", 3.0, 16000)
    before = _mean_volume(film)

    encoder._mix_bgm_bed(film, bed, tmp_path / "work")

    media = probe_mod.probe(film)
    assert media.duration_s == pytest.approx(1.0, abs=0.3), "循环补齐不改变成片时长"
    after = _mean_volume(film)
    assert after > before + 5.0, f"叠床后能量应显著升高（{before:.1f} → {after:.1f}）"


def test_bgm_bed_raises_on_broken_track(tmp_path: Path) -> None:
    """坏曲目（文本冒充音频）：_mix_bgm_bed 如实抛——吞掉是 _export_plan_once 的职责。"""
    film = _as_film(_write_tone_wav(tmp_path / "film.wav", 1.0, 8000), tmp_path / "film.mp4")
    broken = tmp_path / "bed.mp3"
    broken.write_text("这不是音频", encoding="utf-8")
    with pytest.raises(Exception):  # noqa: B017 - ffmpeg 对坏输入的异常类型不承诺
        encoder._mix_bgm_bed(film, broken, tmp_path / "work")
