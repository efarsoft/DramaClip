"""能量扫描 numpy 化的数值契约：与纯 Python 参考实现逐位一致（不是近似）。

间隙阈值（_MIN_PAUSE_S 等）经活库 43 处对拍定值——能量算法若有一位漂移，
切点就会悄悄移动。这里用随机 + 边界采样钉死两条路径的同源性。
"""

from __future__ import annotations

import random
import sys

from dramaclip.engines.analysis.pause_split import _frame_energies, _frame_energies_python


def test_numpy_path_bit_identical_to_python_reference() -> None:
    rng = random.Random(20261024)
    frame_bytes = 480  # 16k × 30ms × 2
    pcm = bytes(rng.randrange(256) for _ in range(frame_bytes * 137))
    # 边界值与静音混入：极值平方的 int64 累加是逐位一致的关键场景
    pcm += (-32768).to_bytes(2, "little", signed=True) * 480
    pcm += b"\x00\x00" * (frame_bytes // 2)
    pcm += (32767).to_bytes(2, "little", signed=True) * 240

    assert _frame_energies(pcm, frame_bytes) == _frame_energies_python(pcm, frame_bytes)


def test_tail_bytes_beyond_last_frame_are_dropped_identically() -> None:
    rng = random.Random(7)
    frame_bytes = 480
    pcm = bytes(rng.randrange(256) for _ in range(frame_bytes * 5 + 137))  # 137 字节零头
    assert _frame_energies(pcm, frame_bytes) == _frame_energies_python(pcm, frame_bytes)
    assert len(_frame_energies(pcm, frame_bytes)) == 5


def test_shorter_than_one_frame_returns_empty() -> None:
    assert _frame_energies(b"\x01\x02", 480) == []


def test_degrades_to_python_when_numpy_missing(
    monkeypatch: object,
) -> None:
    """numpy 缺失（残缺安装）回退纯 int 循环：慢但不炸、结果同源。"""

    monkeypatch.setitem(sys.modules, "numpy", None)  # import numpy → ImportError
    rng = random.Random(3)
    frame_bytes = 480
    pcm = bytes(rng.randrange(256) for _ in range(frame_bytes * 11))
    assert _frame_energies(pcm, frame_bytes) == _frame_energies_python(pcm, frame_bytes)
