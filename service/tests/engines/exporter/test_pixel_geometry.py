"""成片画面几何：交付段与成片必须是**标准 9:16、像素比 1:1**，且逐段一致。

回归动机（2026-09-24 分析批次）：`cut_segment_args` 的滤镜链只做
`scale→crop→eq→scale(出画尺寸)→setpts`，**从不归一样本宽高比（SAR）**。ffmpeg 的
`scale` 保留输入 SAR，于是带非方形像素的源（DVD/电视 rip 的 704×576 SAR 4:3 是典型）
会产出「存储 1080×1920、显示比例却是 0.75」的片子——播放器按元数据把画面横向拉宽
约 33%，烧进去的 ASS 字幕（PlayRes 1080×1920）跟着一起变形。

而且它**逐段漂移**：末级 `scale` 的目标尺寸来自微缩放抖动的取整结果，换一颗随机种子
就换一个 SAR（修复前实测同一段源三颗种子 → `20768:15579` / `149248:112023` /
`93632:70227`）。Phase B 是 `-c copy` 流复制，而段流签名过去不含 SAR，于是"一条片子
里逐段换几何"完全静默。这是音频侧声道布局缺陷（`test_mix.py::
test_delivered_track_has_one_channel_layout`）的视频孪生，量法也照它：**量产物，不量命令**。

手边三部真剧共 30 个文件实测全是 `1080x1920 / SAR 1:1`，所以本仓现网素材不触发；
用例用 lavfi 自造非方形源，不依赖外部素材。
"""

from __future__ import annotations

import json
import random
import subprocess  # noqa: S404 - 参数为受控列表
from pathlib import Path

import pytest

from dramaclip.engines.exporter import encoder

_OUT_W, _OUT_H = encoder._DEFAULT_OUT_SIZE


def _ffmpeg(repo_root: Path) -> str:
    from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg

    return resolve_ffmpeg()


def _sh(ffmpeg: str, args: list[str]) -> None:
    proc = subprocess.run(  # noqa: S603
        [ffmpeg, *args], capture_output=True, text=True, encoding="utf-8",
        errors="replace", check=False, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr[-800:]


def _probe_stream(repo_root: Path, path: Path) -> dict[str, str]:
    """第一路视频流的宽高与像素比（ffprobe 原样字符串）。"""
    from dramaclip.infra.ffmpeg.binaries import resolve_ffprobe

    ffprobe = resolve_ffprobe()
    proc = subprocess.run(  # noqa: S603
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-print_format", "json",
         "-show_entries", "stream=width,height,sample_aspect_ratio,display_aspect_ratio",
         str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr[-800:]

    streams = json.loads(proc.stdout).get("streams") or []
    assert streams, f"{path.name} 没有视频流，用例在量空气"
    return {str(k): str(v) for k, v in streams[0].items()}


@pytest.fixture(scope="module")
def anamorphic_source(
    tmp_path_factory: pytest.TempPathFactory, repo_root: Path
) -> Path:
    """704×576、SAR 4:3（显示 1024×576）的非方形源，带一条音轨。"""
    src = tmp_path_factory.mktemp("geometry") / "anam.mp4"
    _sh(_ffmpeg(repo_root), [
        "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc=size=704x576:rate=25:duration=6",
        "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=6",
        "-vf", "setsar=4/3", "-pix_fmt", "yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
        "-shortest", str(src),
    ])
    assert _probe_stream(repo_root, src)["sample_aspect_ratio"] == "4:3", (
        "自造源没带上非方形像素，用例退化成量方形源（永远绿）"
    )
    return src


@pytest.fixture(scope="module")
def delivered_segments(
    anamorphic_source: Path, tmp_path_factory: pytest.TempPathFactory, repo_root: Path
) -> list[Path]:
    """三种段各出一段：原声直通、旁白混音、衬底混音——两分支共用同一条视频滤镜链。"""
    work_dir = tmp_path_factory.mktemp("delivered")
    tts = work_dir / "tts.wav"
    _sh(_ffmpeg(repo_root), [
        "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", "sine=frequency=440:sample_rate=48000:duration=3", str(tts),
    ])
    segments: list[Path] = []
    for index, audio in enumerate(("original", "narration", "ducked")):
        segment = work_dir / f"seg_{index:03d}.mp4"
        _sh(_ffmpeg(repo_root), encoder.cut_segment_args(
            str(anamorphic_source), str(segment), start=1.0, end=4.0, audio=audio,
            tts_audio=None if audio == "original" else str(tts),
            rng=random.Random(index),
        ))
        segments.append(segment)
    return segments


def _assert_square_16_9(readings: dict[str, dict[str, str]]) -> None:
    """每份产物都必须是 1080×1920 / SAR 1:1 / DAR 9:16，读数以文件名为键。"""
    bad = {
        name: {k: info.get(k, "-") for k in
               ("width", "height", "sample_aspect_ratio", "display_aspect_ratio")}
        for name, info in readings.items()
        if (info.get("width"), info.get("height"), info.get("sample_aspect_ratio"))
        != (str(_OUT_W), str(_OUT_H), "1:1")
    }
    assert not bad, (
        "交付产物像素比未归一（存储尺寸对、显示比例错＝播放器横向拉伸，"
        f"烧录字幕同步变形）：{bad}"
    )


def test_each_delivered_segment_is_geometrically_uniform(
    delivered_segments: list[Path], repo_root: Path
) -> None:
    """逐段：非方形源进来的每一段都必须是标准 1080×1920 / 1:1。"""
    _assert_square_16_9({
        seg.name: _probe_stream(repo_root, seg) for seg in delivered_segments
    })


def test_concat_film_keeps_one_pixel_geometry(
    delivered_segments: list[Path], tmp_path: Path, repo_root: Path
) -> None:
    """成片：流复制拼出来的片子既不能中途换几何，也不能整片带非方形比。"""
    film = tmp_path / "film.mp4"
    encoder._concat(delivered_segments, film)
    per_segment = {seg.name: _probe_stream(repo_root, seg) for seg in delivered_segments}
    _assert_square_16_9({**per_segment, film.name: _probe_stream(repo_root, film)})
    geometries = {
        (info.get("width"), info.get("height"), info.get("sample_aspect_ratio"))
        for info in per_segment.values()
    }
    assert len(geometries) == 1, f"段间几何不一致，-c copy 会照单拼进同一条流：{geometries}"
