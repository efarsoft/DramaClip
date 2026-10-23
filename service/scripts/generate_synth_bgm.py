"""程序化 BGM 生成（兜底床）：numpy 直出 wav → ogg 入曲库，五情绪各 3 首变奏。

定位（业主裁决）：兜底层，不是主力——合成器质感做不了编曲，但无缝循环、
时长精确、和声配方可控是下载曲没有的优势。全部振荡器频率对齐「总长整数周期」、
节拍网格整除总长，循环点无跳变；峰值归一 -12dBFS 防削波（多层叠加）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

SR = 44100
OUT_ROOT = Path(r"C:\Users\efarh\AppData\Roaming\DramaClip\bgm")


def _align(freq: float, n_samples: int) -> float:
    """频率对齐为总长内整数周期：循环点相位连续的充要条件。"""
    cycles = max(round(freq * n_samples / SR), 1)
    return cycles * SR / n_samples


def _tone(
    freq: float, n: int, amp: float, harmonics: tuple[tuple[float, float], ...] = ((1.0, 1.0),),
) -> np.ndarray:
    t = np.arange(n) / SR
    f = _align(freq, n)
    return amp * sum(a * np.sin(2 * np.pi * f * h * t) for h, a in harmonics)


def _detune_pair(freq: float, n: int, amp: float, cents: float = 6.0) -> np.ndarray:
    """左右微失谐的和弦宽度（单声道合成时做拍频宽度）。"""
    ratio = 2 ** (cents / 1200)
    return _tone(freq, n, amp) + _tone(freq * ratio, n, amp)


def _breath(n: int, rate_hz: float, depth: float = 0.25) -> np.ndarray:
    """慢呼吸调制（音量 LFO），周期对齐总长。"""
    t = np.arange(n) / SR
    return 1.0 - depth * 0.5 * (1 - np.cos(2 * np.pi * _align(rate_hz, n) * t))


def _pulse(n: int, rate_hz: float, depth: float = 0.5) -> np.ndarray:
    """节奏脉冲（升余弦平滑），天然无缝循环。"""
    t = np.arange(n) / SR
    wave = 0.5 - 0.5 * np.cos(2 * np.pi * _align(rate_hz, n) * t)
    return 1.0 - depth * wave ** 2


def _arp(n: int, freqs: list[float], step_s: float, amp: float, release: float = 0.6) -> np.ndarray:
    """琶音：音符网格整除总长，短音+指数式（升余弦）释放。"""
    step = int(step_s * SR)
    assert n % step == 0, "总长必须整除琶音步长（无缝循环）"
    out = np.zeros(n)
    note_n = int(step * release)
    env = 0.5 + 0.5 * np.cos(np.linspace(np.pi, 2 * np.pi, note_n))
    for i, start in enumerate(range(0, n, step)):
        f = _align(freqs[i % len(freqs)], n)
        seg = min(note_n, n - start)
        out[start : start + seg] += amp * env[:seg] * np.sin(2 * np.pi * f * np.arange(seg) / SR)
    return out


def _normalize(mix: np.ndarray, peak_db: float = -12.0) -> np.ndarray:
    peak = float(np.max(np.abs(mix))) or 1.0
    return mix * (10 ** (peak_db / 20)) / peak


def _render(spec_name: str, emotion: str, duration_s: float, builder) -> Path:
    n = int(SR * duration_s)
    mix = _normalize(builder(n))
    wav = OUT_ROOT / emotion / f"_tmp_{spec_name}.wav"
    wav.parent.mkdir(parents=True, exist_ok=True)
    import wave

    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes((mix * 32767).astype("<i2").tobytes())
    ogg = OUT_ROOT / emotion / f"Synth Pad {spec_name}.ogg"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", str(wav), "-c:a", "libvorbis", "-q:a", "6", str(ogg)],
        check=True, capture_output=True,
    )
    wav.unlink()
    return ogg


# ---- 五情绪配方：root 变奏 ×3 -----------------------------------------------

def _pad_chord(n: int, root: float, intervals: tuple[float, ...], amp: float) -> np.ndarray:
    return sum(_detune_pair(root * ratio, n, amp) for ratio in intervals)


RECIPES = {
    # default：中性叙事 pad，大三/小三和弦慢呼吸
    "default": [
        (lambda n: _pad_chord(n, 130.81, (1.0, 1.5, 2.0), 0.20) * _breath(n, 0.05), 172.0),
        (lambda n: _pad_chord(n, 146.83, (1.0, 1.19, 1.5), 0.20) * _breath(n, 0.04), 184.0),
        (lambda n: _pad_chord(n, 174.61, (1.0, 1.25, 1.5), 0.18) * _breath(n, 0.06), 163.0),
    ],
    # suspense：小调低音 + 失谐拍频（不协和悬置）+ 心跳脉动（_pulse 自动对齐时长）
    "suspense": [
        (lambda n: (
            _pad_chord(n, 73.42, (1.0, 1.06, 1.5), 0.22)
            + _detune_pair(146.83, n, 0.10, cents=35.0)
        ) * _pulse(n, 1.8, 0.30), 172.0),
        (lambda n: (
            _pad_chord(n, 82.41, (1.0, 1.06, 1.49), 0.22)
            + _detune_pair(164.81, n, 0.10, cents=40.0)
        ) * _pulse(n, 1.5, 0.35), 184.0),
        (lambda n: _pad_chord(n, 65.41, (1.0, 1.05, 1.5), 0.24) * _pulse(n, 2.0, 0.25), 163.0),
    ],
    # anger：锯齿感低音（奇次谐波）+ 四分音符脉冲 + 小二度摩擦
    "anger": [
        (lambda n: (
            _tone(87.31, n, 0.20, harmonics=((1, 1.0), (3, 0.35), (5, 0.15)))
            + _pad_chord(n, 87.31, (1.0, 1.06), 0.10)
        ) * _pulse(n, 2.0, 0.55), 172.0),
        (lambda n: (
            _tone(98.0, n, 0.20, harmonics=((1, 1.0), (3, 0.30), (5, 0.12)))
            + _pad_chord(n, 98.0, (1.0, 1.06), 0.10)
        ) * _pulse(n, 2.2, 0.50), 184.0),
        (lambda n: (
            _tone(73.42, n, 0.22, harmonics=((1, 1.0), (3, 0.35), (7, 0.10)))
        ) * _pulse(n, 1.8, 0.60), 163.0),
    ],
    # triumph：大调和弦 + 上行大调琶音（推进感）——时长整除琶音步长
    "triumph": [
        (lambda n: (
            _pad_chord(n, 130.81, (1.0, 1.25, 1.5), 0.16)
            + _arp(n, [130.81, 163.81, 196.0, 261.63], 1.0, 0.10)
        ) * _breath(n, 0.08, 0.15), 172.0),
        (lambda n: (
            _pad_chord(n, 146.83, (1.0, 1.25, 1.5), 0.16)
            + _arp(n, [146.83, 185.0, 220.0, 293.66], 0.8, 0.10)
        ) * _breath(n, 0.09, 0.15), 184.0),
        (lambda n: (
            _pad_chord(n, 110.0, (1.0, 1.25, 1.5, 2.0), 0.15)
            + _arp(n, [110.0, 138.59, 164.81, 220.0], 1.2, 0.10)
        ) * _breath(n, 0.07, 0.18), 168.0),
    ],
    # sadness：小调慢琶音 + 低音持续，大量留白（低能量）——时长整除琶音步长
    "sadness": [
        (lambda n: (
            _pad_chord(n, 110.0, (1.0, 1.5), 0.14)
            + _arp(n, [220.0, 261.63, 329.63], 2.0, 0.07, release=0.9)
        ), 180.0),
        (lambda n: (
            _pad_chord(n, 98.0, (1.0, 1.5), 0.14)
            + _arp(n, [196.0, 233.08, 293.66], 2.4, 0.07, release=0.9)
        ), 168.0),
        (lambda n: (
            _pad_chord(n, 130.81, (1.0, 1.19, 1.5), 0.12)
            + _arp(n, [261.63, 311.13, 392.0], 2.2, 0.06, release=0.9)
        ), 176.0),
    ],
}


def main() -> None:
    made: list[Path] = []
    for emotion, variants in RECIPES.items():
        for index, (builder, duration) in enumerate(variants, start=1):
            path = _render(f"{index:02d}", emotion, duration, builder)
            made.append(path)
            print(f"OK {path.relative_to(OUT_ROOT)}")
    print(f"共 {len(made)} 首")


if __name__ == "__main__":
    main()
