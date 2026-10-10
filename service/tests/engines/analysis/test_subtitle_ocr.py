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
    assert segments[0].end == 1.5, "邻条各让到采样中点，不各补各的 1.0s"
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


# ---- 条驻留区间：标点噪声与补时重叠（2026-10-09 真机 ep1 取证）----
#
# 两条独立的病，同一处修：
# 1) 标点参与相似度判据 → 同一条字幕因描边碎符号裂成两条。真机 42~43s 实测
#    「他的皇节早就包经换了一个人，」/「～，。他的皇节早就已经换了一个人」
#    原文相似度 0.80 < 阈值 0.85 判不延续；去标点后 0.96 判延续。
# 2) 头尾补时（-0.5/+1.0）逐条独立补 → 相邻条必然重叠：台词连着念时条间隔就是
#    采样间隔 1s，而补量合计 1.5s。真机 ep1 28 条里 13 对重叠。修法不是调小常量
#    （拍阈值），是按邻条位置划分间隔——重叠在构造上不可能，空白间隔照旧补满。


def test_merge_runs_punctuation_jitter_joins_and_strips() -> None:
    boxes = lambda t: [(t, 0.66, 0.68, 0.9)]  # noqa: E731
    results = [
        (42.0, boxes("他的皇节早就包经换了一个人，")),
        (43.0, boxes("～，。他的皇节早就已经换了一个人")),
    ]
    segments = _merge_runs(results)
    assert [s.text for s in segments] == ["他的皇节早就包经换了一个人"], (
        "标点不是台词语义：判延续前先剥，条文本里也不留碎符号"
    )


def test_merge_runs_adjacent_bars_never_overlap() -> None:
    boxes = lambda t: [(t, 0.66, 0.68, 0.9)]  # noqa: E731
    results = [(float(i), boxes(f"第{i}句台词")) for i in range(4)]
    bars = _merge_runs(results)
    assert len(bars) == 4
    for index in range(len(bars) - 1):
        prev, nxt = bars[index], bars[index + 1]
        assert nxt.start >= prev.end, f"驻留窗重叠：{prev} / {nxt}"
    assert (bars[0].start, bars[0].end) == (0.0, 0.5)
    assert (bars[1].start, bars[1].end) == (0.5, 1.5)
    assert (bars[3].start, bars[3].end) == (2.5, 4.0), "末条无邻条，尾补按消失延迟补满"


def test_merge_runs_keeps_padding_across_blank_frames() -> None:
    """隔了空白帧的邻条不挤窄补时：起止误差兜底要留够，否则擦除窗早关漏擦。"""
    boxes = lambda t: [(t, 0.66, 0.68, 0.9)]  # noqa: E731
    results = [(0.0, boxes("你好")), (1.0, []), (2.0, []), (3.0, boxes("再见"))]
    bars = _merge_runs(results)
    assert [b.text for b in bars] == ["你好", "再见"]
    assert bars[0].end == 1.0, "间隔 3s > 补量：尾补满 1.0s"
    assert bars[1].start == 2.5, "头补 0.5s 是采样间隔的一半，不是邻条边界"


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


# ---- 台词行形状闸（2026-10-09 业主裁决 B：位置不做判据，形状做判据）----
#
# 「字幕不许落在画面中间」与「字幕精准覆盖原字幕」在源字幕本就烧在中部时互斥。
# 业主选覆盖优先，于是信任判据只剩形状与跨帧强度：一条真台词行的行框高度是
# 有界的（真机 10 集实测 0.094–0.108），而误检聚合（两行 OCR 合并、片头字幕墙、
# 道具字据整页）高度翻倍。位置不是证据——横屏剧把字幕烧在 0.55 也是真字幕。


def test_line_is_caption_row_shape_gate() -> None:
    f = subtitle_ocr.line_is_caption_row
    assert f((0.809, 0.903)) is True  # 第6集真机行框 h=0.094
    assert f((0.798, 0.906)) is True  # 第2集真机行框 h=0.108（十集里最宽的一档）
    assert f((0.619, 0.772)) is False  # 第6集存量脏行 h=0.153，正糊在下半张脸
    assert f((0.840, 0.856)) is False  # 切镜半帧采到的标点残迹


def test_cluster_lines_drops_out_of_shape_rows() -> None:
    """带心在台词带内、但高度不像一行台词（两行 OCR 合并成一条高框）→ 不擦。"""
    candidates = [(0.820, 0.891), (0.620, 0.760)]
    lines = subtitle_ocr._cluster_lines(candidates, (0.600, 0.930))
    assert [(round(b.top, 3), round(b.bottom, 3)) for b in lines] == [(0.812, 0.899)]


# ---- 单帧道具文字幕墙不得定带（2026-10-09 真机 ep6 满屏误擦） ----
#
# 台词字幕是「跨帧持续出现在同一位置」的通道；一帧里密集出现的竖排/整页
# 文字（银票字据、片头字幕墙）只在该帧存在。旧实现按**框数**投票，一帧
# 8 个框盖过 4 帧各 1 个真台词框 → 带定到脸上、擦除糊脸、真台词留在屏上。


def _probes_with_prop_page() -> list[subtitle_ocr.FrameResult]:
    """10 探针帧：4 帧底部台词、其中 1 帧另有整页字据（8 个高框）。"""
    frames: list[subtitle_ocr.FrameResult] = [[] for _ in range(10)]
    for i, index in enumerate((0, 3, 5, 8)):
        frames[index] = [(f"台词{i}", 0.820, 0.891, 0.8)]
    frames[1] = [
        ("此银雨整", 0.413, 0.619, 0.81),
        ("以解燃眉之急", 0.407, 0.693, 0.83),
        ("皇后私扣一半", 0.416, 0.714, 0.72),
        ("国丈自认", 0.437, 0.584, 0.52),
        ("双贵于京城", 0.431, 0.652, 0.60),
        ("皇后變賣首飾", 0.431, 0.732, 0.59),
        ("今有同凭", 0.475, 0.669, 0.52),
        ("家业不无", 0.627, 0.764, 0.55),
    ]
    return frames


def test_pick_band_ignores_single_frame_prop_page() -> None:
    band = _pick_band(_probes_with_prop_page())
    assert band is not None
    assert band.top >= 0.7, f"带被单帧字据定到脸上了：{band}"
    assert band.bottom <= 0.95


def test_prop_page_never_reaches_line_rects() -> None:
    """整条 producer 链：字据框既不进带，也不进行框（否则 delogo 糊脸）。"""
    probes = _probes_with_prop_page()
    candidates = subtitle_ocr._dialogue_candidates(probes)
    band = subtitle_ocr._band_from(candidates)
    assert band is not None
    lines = subtitle_ocr._cluster_lines(candidates, band)
    assert [(round(b.top, 3), round(b.bottom, 3)) for b in lines] == [(0.812, 0.899)]
