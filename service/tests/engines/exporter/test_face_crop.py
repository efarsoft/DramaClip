"""9:16 人脸跟随裁剪：无检测时保持中心裁，有比例时偏移裁窗。"""

from __future__ import annotations

import random
import re
from pathlib import Path

import pytest

from dramaclip.engines.exporter.encoder import cut_segment_args
from dramaclip.engines.exporter.face_crop import face_x_ratio

_CENTER_CROP = re.compile(r"(?:^|,)crop=\d+:\d+(?:,|$)")


def _vf(args: list[str]) -> str:
    return args[args.index("-vf") + 1]


def test_center_crop_when_no_ratio() -> None:
    args = cut_segment_args(
        "src.mp4",
        "seg.mp4",
        start=1.5,
        end=8.25,
        audio="original",
        tts_audio=None,
        rng=random.Random(42),
    )
    vf = _vf(args)
    assert _CENTER_CROP.search(vf), vf


def test_crop_uses_face_ratio() -> None:
    args = cut_segment_args(
        "src.mp4",
        "seg.mp4",
        start=1.5,
        end=8.25,
        audio="original",
        tts_audio=None,
        rng=random.Random(42),
        crop_x_ratio=0.2,
    )
    vf = _vf(args)
    assert not _CENTER_CROP.search(vf), vf
    assert "0.2" in vf


def test_face_x_ratio_none_without_cv2(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def blocked(name: str, *args: object, **kwargs: object) -> object:
        if name == "cv2":
            raise ImportError("blocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    assert face_x_ratio(Path("missing.mp4"), 1.0) is None


def test_face_x_ratio_none_without_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """模型文件缺失 → None（中心裁兜底），不是崩在 FaceDetectorYN.create。

    opencv 5.0 的 cv2 不带 Haar XML；YuNet 模型是随包资源，丢了必须静默降级。
    """
    import dramaclip.engines.exporter.face_crop as face_crop

    monkeypatch.setattr(face_crop, "_YUNET_MODEL", tmp_path / "gone.onnx")
    assert face_x_ratio(Path("missing.mp4"), 1.0) is None


def test_face_x_ratio_detects_real_face() -> None:
    """真机正样本：合成一张带正脸的图 → 视频，检测必须给出中心比例。

    模型没随包就跳过（CI 全新检出含 resources/，本地缺文件才是真问题）。
    回归对象：旧 Haar 实现在 opencv 5.0 上**永远**返回 None——检测器不存在、
    级联 XML 也没有，跟脸裁切形同虚设却无任何报错。
    """
    import shutil
    import subprocess
    import tempfile
    from urllib.request import urlretrieve

    if not face_crop_model_exists():
        pytest.skip("YuNet 模型未随包")
    ffmpeg = shutil.which("ffmpeg") or str(
        Path(__file__).resolve().parents[4] / "resources" / "ffmpeg" / "ffmpeg.exe"
    )
    with tempfile.TemporaryDirectory() as tmp:
        face_jpg = Path(tmp) / "face.jpg"
        try:
            urlretrieve(
                "https://raw.githubusercontent.com/opencv/opencv/master/samples/data/lena.jpg",
                face_jpg,
            )
        except Exception:
            pytest.skip("正样本下载失败（离线环境）")
        video = Path(tmp) / "face.mp4"
        subprocess.run(
            [
                ffmpeg, "-y", "-loop", "1", "-i", str(face_jpg),
                "-t", "0.5", "-pix_fmt", "yuv420p", str(video),
            ],
            capture_output=True,
            check=True,
        )
        ratio = face_x_ratio(video, 0.1)
    assert ratio is not None, "带正脸的视频必须检出脸（检出 None = 检测器失效的形状）"
    assert 0.3 < ratio < 0.8


def face_crop_model_exists() -> bool:
    from dramaclip.engines.exporter.face_crop import _YUNET_MODEL

    return _YUNET_MODEL.is_file()
