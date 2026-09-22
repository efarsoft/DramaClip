"""9:16 人脸跟随：取最大脸水平中心比例；缺依赖/缺模型/失败一律返回 None（中心裁）。

检测器选 YuNet（`cv2.FaceDetectorYN`），不是 Haar 级联：
- 本机 opencv 5.0 已删 `cv2.CascadeClassifier`，且随包 `cv2/data` 里没有 haar XML，
  旧写法在这套环境里 **永远静默降级**成中心裁（`hasattr(cv2,'CascadeClassifier')` 为 False）；
- YuNet 是 DNN 检测器，模型单文件（`resources/face-detect/*.onnx`）随包分发，
  不依赖系统里装没装、opencv 版本带不带级联 XML；
- 侧脸/低分辨率鲁棒性也优于 Haar 级联。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from dramaclip.infra.ffmpeg import runner
from dramaclip.infra.paths import resolve_resources_dir

# YuNet 模型随包路径（一处真相）；换模型只需替换这个文件。
_YUNET_MODEL = resolve_resources_dir() / "face-detect" / "face_detection_yunet_2023mar.onnx"


def face_x_ratio(video_path: Path, time_s: float) -> float | None:
    """视频在 `time_s` 处最大脸的水平中心比例（0–1）；拿不到脸/依赖/模型时 None。"""
    try:
        import cv2  # ml extras 懒加载
    except ImportError:
        return None
    if not _YUNET_MODEL.is_file():
        return None
    try:
        detector = cv2.FaceDetectorYN.create(
            str(_YUNET_MODEL), "", (320, 320), score_threshold=0.6, nms_threshold=0.3
        )
    except Exception:  # noqa: BLE001 - 模型加载失败一律中心裁
        return None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            frame_path = Path(tmp) / "frame.jpg"
            try:
                runner.run(
                    [
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-ss",
                        f"{max(time_s, 0.0):.3f}",
                        "-i",
                        str(video_path),
                        "-vframes",
                        "1",
                        str(frame_path),
                    ],
                    timeout_s=30,
                )
            except runner.FfmpegError:
                return None
            if not frame_path.is_file():
                return None
            image = cv2.imread(str(frame_path))
        if image is None:
            return None
        height, width = image.shape[:2]
        if width <= 0:
            return None
        # setInputSize 必须等于实际帧尺寸，否则 detect 坐标会错位。
        detector.setInputSize((width, height))
        _retval, faces = detector.detect(image)
        if faces is None or len(faces) == 0:
            return None
        # YuNet 行格式：[x, y, w, h, 5×关键点, score]；取面积最大那张脸。
        best = max(faces, key=lambda f: float(f[2]) * float(f[3]))
        center_x = (float(best[0]) + float(best[2]) / 2.0) / float(width)
        return min(1.0, max(0.0, center_x))
    except Exception:  # noqa: BLE001 - 检测失败一律中心裁
        return None
