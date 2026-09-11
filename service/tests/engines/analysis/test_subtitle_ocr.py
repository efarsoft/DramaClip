"""subtitle_ocr：字幕带定位与字幕条合并（纯函数，OCR 可注入）。"""

from __future__ import annotations

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
