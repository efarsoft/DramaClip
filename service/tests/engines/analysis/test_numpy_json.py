"""numpy 泄漏防线：band/lines 落库前收成 python float，_dumps 兜底不可序列化标量。

真机 2026-10-20：rapidocr 3.x 框坐标是 np.float32，经 _Band 复合运算后原样进
subtitle_band 的裸 dict json.dumps——十集连挂「Object of type float32 is not
JSON serializable」。旧环境侥幸活着的根因是包版本差，防线必须是结构性的。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from dramaclip.api.analysis_job import _dumps
from dramaclip.engines.analysis.subtitle_ocr import detect_band, extract_subtitles

pytest.importorskip("rapidocr", reason="numpy 桩复刻 rapidocr 3.x 的 float32 坐标")

# numpy 桩：坐标全 float32，复刻真机 rapidocr 3.x 的返回形状；
# 文字逐帧更换（同位置换字=真台词，同位置同字会被当常驻横幅剔除）


def _np_ocr_factory():
    counter = {"n": 0}

    def _ocr(_frame: str) -> list[tuple[str, float, float, float]]:
        counter["n"] += 1
        box = np.float32(0.82)
        return [(f"台词{counter['n']}", float(box) - np.float32(0.02), box, np.float32(0.97))]

    return _ocr


@pytest.fixture()
def ocr_video(tmp_path: Path) -> Any:
    """能被 ffmpeg 抽帧的迷你视频（复用 contact_sheet 的合成手法，2 秒纯色）。"""
    from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg

    video = tmp_path / "ocr.mp4"
    import subprocess  # noqa: S404

    subprocess.run(  # noqa: S603
        [
            resolve_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=320x180:d=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
        ],
        check=True,
    )
    return video


def test_detect_band_returns_plain_floats(ocr_video: Path, tmp_path: Path) -> None:
    band = detect_band(ocr_video, tmp_path, duration_s=2.0, ocr=_np_ocr_factory())
    assert band is not None
    assert type(band[0]) is float and type(band[1]) is float, (
        f"band 必须是 python float，实得 {type(band[0])}/{type(band[1])}——"
        "np.float32 进裸 dict json.dumps 会炸"
    )


def test_extract_subtitles_band_and_lines_are_plain_floats(
    ocr_video: Path, tmp_path: Path
) -> None:
    segments, band, lines = extract_subtitles(
        ocr_video, tmp_path, duration_s=2.0, ocr=_np_ocr_factory()
    )
    assert band is not None and type(band[0]) is float and type(band[1]) is float
    if lines:
        assert all(type(a) is float and type(b) is float for a, b in lines)


def test_dumps_survives_numpy_scalars() -> None:
    class _HasItem:
        def item(self) -> float:
            return 0.82

    assert _dumps({"band": [_HasItem(), 0.5]}) == '{"band": [0.82, 0.5]}'
    with pytest.raises(TypeError):
        _dumps({"bad": object()})
