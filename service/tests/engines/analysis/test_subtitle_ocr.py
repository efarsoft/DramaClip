"""subtitle_ocr：字幕带定位与字幕条合并（纯函数，OCR 可注入）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dramaclip.engines.analysis import subtitle_ocr
from dramaclip.engines.analysis.subtitle_ocr import _Band, _merge_runs, _pick_band

_B = _Band(top=0.6, bottom=0.72)


def _probes_with_banner() -> list[list[tuple[str, float, float, float]]]:
    """4 个探针帧：免责横幅（常驻）+ 逐帧变化的台词字幕（65% 高度）。"""
    probes = []
    for index in range(4):
        probes.append(
            [
                ("剧情纯属虚构", 0.94, 0.98, 0.9),
                (f"第{index}句台词", 0.65, 0.68, 0.95),
            ]
        )
    return probes


def test_pick_band_locates_dialogue_and_skips_banner() -> None:
    band = _pick_band(_probes_with_banner())
    assert band is not None
    assert band.top < 0.7 and band.bottom > 0.64


def test_pick_band_all_persistent_returns_none() -> None:
    probes = [[("纯横幅", 0.94, 0.98, 0.9)] for _ in range(4)]
    assert _pick_band(probes) is None


def test_pick_band_empty_probes_returns_none() -> None:
    assert _pick_band([]) is None


def test_merge_runs_joins_same_text() -> None:
    boxes = lambda t, c: [(t, 0.66, 0.68, c)]  # noqa: E731
    results = [
        (0.0, boxes("你好", 0.9)),
        (1.0, boxes("你好", 0.95)),
        (2.0, boxes("再见", 0.9)),
    ]
    segments = _merge_runs(results)
    assert [s.text for s in segments] == ["你好", "再见"]
    assert segments[0].start == 0.0
    assert segments[0].end == 2.0
    assert abs(segments[0].conf - 0.925) < 1e-6


def test_merge_runs_fuzzy_text_joins() -> None:
    boxes = lambda t: [(t, 0.66, 0.68, 0.9)]  # noqa: E731
    results = [(0.0, boxes("这是苍南市的冠军")), (1.0, boxes("这是苍南市的冠军了"))]
    segments = _merge_runs(results)
    assert len(segments) == 1
    assert segments[0].text == "这是苍南市的冠军了"


def test_merge_runs_empty_frame_splits_runs() -> None:
    boxes = lambda t: [(t, 0.66, 0.68, 0.9)]  # noqa: E731
    results = [(0.0, boxes("你好")), (1.0, []), (2.0, boxes("你好"))]
    segments = _merge_runs(results)
    assert len(segments) == 2, "中间无字帧断开运行，不跨帧拼接"


def test_merge_runs_drops_single_char_fragments() -> None:
    boxes = lambda t: [(t, 0.66, 0.68, 0.9)]  # noqa: E731
    results = [(0.0, boxes("你")), (1.0, boxes("你是谁"))]
    segments = _merge_runs(results)
    assert [s.text for s in segments] == ["你是谁"], "单字残条丢弃，不污染对齐"


# ── A2：extract_subtitles 回传探测到的字幕带（用完即弃 → 落库避让）────────────
#
# ffmpeg 探针/裁帧不打真帧：monkeypatch 掉 _probe_frames/_sample_frames，
# 只验「探到的 band 必须跟着 segments 一起回来」这条数据链。

def test_extract_subtitles_returns_detected_band(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    probes = [[(f"第{i}句台词", 0.65, 0.68, 0.95)] for i in range(4)]
    monkeypatch.setattr(
        subtitle_ocr, "_probe_frames", lambda *_a, **_k: [(0.5, p) for p in probes]
    )
    monkeypatch.setattr(subtitle_ocr, "_sample_frames", lambda *_a, **_k: [])
    segments, band, lines = subtitle_ocr.extract_subtitles(
        Path("fake.mp4"), tmp_path, duration_s=3.0, ocr=lambda _p: []
    )
    assert segments == []
    assert band is not None, "探测到的字幕带必须回传，不能用完即弃"
    assert band[0] <= 0.65 and band[1] >= 0.68, "回传的 band 覆盖探针实测位置"
    assert lines is not None and lines[0][0] <= 0.65, "行框同样回传（逐行擦除用）"


def test_extract_subtitles_band_none_when_not_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subtitle_ocr, "_probe_frames", lambda *_a, **_k: [])
    monkeypatch.setattr(subtitle_ocr, "_sample_frames", lambda *_a, **_k: [])
    segments, band, lines = subtitle_ocr.extract_subtitles(
        Path("fake.mp4"), tmp_path, duration_s=3.0, ocr=lambda _p: []
    )
    assert segments == [] and band is None and lines is None, (
        "未探到带 → band/行框均为 None（NULL 语义）"
    )


def test_extract_subtitles_passes_through_given_band(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_probe(*_a: object, **_k: object) -> object:
        raise AssertionError("外部已给 band，不应再探")

    monkeypatch.setattr(subtitle_ocr, "_probe_frames", forbidden_probe)
    monkeypatch.setattr(subtitle_ocr, "_sample_frames", lambda *_a, **_k: [])
    segments, band, lines = subtitle_ocr.extract_subtitles(
        Path("fake.mp4"), tmp_path, duration_s=3.0, ocr=lambda _p: [], band=(0.5, 0.6)
    )
    assert segments == []
    assert band == (0.5, 0.6), "外部传入的 band 原样回传（调用方拿它落库）"
    assert lines is None, "外部传入 band 时行框未知，回 None（调用方按整带回退）"


# ---- 逐行擦除框：贴字不贴带 + 花字/道具字不进擦除集（2026-10-07 审计） ----


def test_cluster_lines_stroke_margin_not_band_expand() -> None:
    """行框余量是描边级（0.008≈15px），不是整带包络的 0.04（77px）——
    此前逐行框吃 _BAND_EXPAND，矩形比文字高 3 倍，delogo 直接够到嘴。"""
    candidates = [(0.653, 0.696), (0.660, 0.700)]
    lines = subtitle_ocr._cluster_lines(candidates, (0.613, 0.740))
    assert len(lines) == 1
    assert abs(lines[0].top - (0.653 - 0.008)) < 1e-6
    assert abs(lines[0].bottom - (0.700 + 0.008)) < 1e-6


def test_cluster_lines_filters_decorative_text_by_band() -> None:
    """真机 ep9 三脏行：竖排花字人物卡 (0.089,0.263)、道具招幌「芋萬」
    (0.199,0.413) 都是画面真实文字——但不是台词字幕，禁止进擦除集。"""
    candidates = [(0.089, 0.263), (0.199, 0.413), (0.653, 0.696), (0.660, 0.700)]
    lines = subtitle_ocr._cluster_lines(candidates, (0.613, 0.740))
    assert [(round(b.top, 3), round(b.bottom, 3)) for b in lines] == [
        (round(0.653 - 0.008, 3), round(0.700 + 0.008, 3))
    ], "只有台词带内的行能进擦除集"


def test_line_in_dialogue_band_shared_predicate() -> None:
    """共享谓词：export 读取端用它对存量行框再夹一次，两边永不漂移。"""
    f = subtitle_ocr.line_in_dialogue_band
    assert f((0.653, 0.696), (0.613, 0.740)) is True
    assert f((0.089, 0.263), (0.613, 0.740)) is False
    assert f((0.199, 0.413), (0.613, 0.740)) is False
