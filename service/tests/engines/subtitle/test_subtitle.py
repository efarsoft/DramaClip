"""engines.subtitle：预设加载 / 情绪匹配 / ASS 生成。"""

from __future__ import annotations

import re
from typing import Any

import pytest

from dramaclip.engines.subtitle import ass_generator, presets
from dramaclip.engines.subtitle.ass_generator import build_ass, split_subtitle_text
from dramaclip.engines.subtitle.emotion_matcher import match_emotion


def test_builtin_presets_loaded() -> None:
    all_presets = presets.list_presets()
    ids = {preset["preset_id"] for preset in all_presets}
    assert {"calm-narrative", "conflict-impact"} <= ids


def test_get_preset_fallback() -> None:
    assert presets.get_preset("nonexistent")["preset_id"] == "conflict-impact"
    assert presets.get_preset("calm-narrative")["preset_id"] == "calm-narrative"


def test_match_emotion_label_and_keywords() -> None:
    assert match_emotion("随便什么", "Angry") == "anger"
    assert match_emotion("你给我滚出去") == "anger"
    assert match_emotion("我终于翻身了") == "triumph"
    assert match_emotion("今天天气不错") == "default"


def test_build_ass_structure() -> None:
    preset = presets.get_preset("conflict-impact")
    ass = build_ass(
        [
            {"start": 0.5, "end": 3.2, "text": "你给我滚出去！"},
            {"start": 4.0, "end": 6.0, "text": ""},
        ],
        preset,
    )
    assert ass.startswith("[Script Info]")
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert "Dialogue: 0,0:00:00.50,0:00:03.20" in ass
    assert "你给我滚出去！" in ass
    assert ass.count("Dialogue:") == 1, "空文本行应被跳过"
    assert "\\fad(200,200)" in ass, "冲突预设淡入 200ms"
    assert "&H000000FF" in ass, "anger 情绪红色"


def test_build_ass_climax_layout_centered() -> None:
    preset = presets.get_preset("conflict-impact")
    ass = build_ass([{"start": 0, "end": 2, "text": "我要报仇！"}], preset)
    # 报仇 → triumph 高潮情绪 → climax 布局 center_single：必须真的居中（\an5），
    # 而不是贴底只留 10px——后者是「字幕下半被裁」的成因。
    assert "\\an5" in ass and "\\fscx112" in ass and "&H0000D7FF" in ass
    assert _event_fields(ass)[7] == "0", "居中对齐下 MarginV 不参与定位，须为 0"


def _event_fields(ass: str, index: int = 0) -> list[str]:
    """第 index 条 Dialogue 的逗号字段（Format 同序：7 是 MarginV）。"""
    lines = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    return lines[index][len("Dialogue: ") :].split(",")


def _style_field(ass: str, index: int) -> str:
    line = next(line for line in ass.splitlines() if line.startswith("Style:"))
    return line[len("Style: ") :].split(",")[index]


def test_layout_dimension_drives_alignment_not_just_margin() -> None:
    """回归守卫：预设的 layout 维度必须落到事件对齐上。

    这条在修复前必红：`_ALIGNMENT` 当时是死代码，Style Alignment 恒为 2（贴底），
    非 bottom_bar 只是把 MarginV 从 90 改成 10 —— 字号 72 的字直接沉出画面底缘。
    """
    by_layout = {
        "bottom_bar": 2,
        "center_single": 5,
        "center_multi": 5,
        "top_title": 8,
    }
    for layout, alignment in by_layout.items():
        preset = {
            "preset_id": "probe",
            "font": {"name": "X", "size": 72, "margin_v": 90},
            "dimensions": {"layout": {"default": layout}},
        }
        ass = build_ass([{"start": 0, "end": 2, "text": "台词"}], preset)
        assert f"\\an{alignment}" in ass, f"{layout} 应给出 \\an{alignment}"
        assert _style_field(ass, 18) == str(alignment), f"{layout} 的 Style Alignment 未跟随"


def test_bottom_bar_keeps_clear_of_frame_edge() -> None:
    """贴底布局的 MarginV 必须是预设留白；10 那档只在居中/置顶时才会出现。"""
    preset = presets.get_preset("conflict-impact")
    ass = build_ass([{"start": 0, "end": 2, "text": "普通台词"}], preset)
    assert _event_fields(ass)[7] == "90", "bottom_bar 用预设 margin_v=90，不是硬编码 10"
    assert "\\an2" in ass


def test_karaoke_pop_default_layout_is_not_bottom_bar() -> None:
    """karaoke-pop 的 layout.default 本就是 center_single：整片每行都该居中。

    修复前它是**每一行**被裁（贴底 + MarginV 10），业主截图即此形状。
    """
    preset = presets.get_preset("karaoke-pop")
    ass = build_ass(
        [
            {"start": 0, "end": 2, "text": "第一行"},
            {"start": 2, "end": 4, "text": "第二行"},
        ],
        preset,
    )
    assert ass.count("\\an5") == 2
    assert "\\an2" not in ass


# --- 长解说拆行（业主立案②：整段一条字幕超长） --------------------------------
#
# `split_subtitle_text` 此前**零直接测试**：它只在 api/export.py 的 burn_subtitle
# 里被调一次，任何一条既有测试都没看过它的返回值。下面先把它的四条分支各自钉住，
# 再把「一行放得下」从口头承诺变成对着 ASS 头部几何算出来的断言。

_NO_PUNCT_RUN = "她怎么也想不到那个温声细语的男人会在新婚夜锁上房门转身就走"
_PUNCTUATED = "她本以为嫁了个老实人，谁知道新婚夜他锁上了门。门外传来婆婆的笑声！"


def _stripped(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _style_field_int(ass: str, index: int) -> int:
    return int(_style_field(ass, index))


def _line_metrics(preset: dict[str, Any]) -> tuple[int, int]:
    """从**生成的 ASS 头部**读 (字号, 一行可用宽度)，不接受口头声明。

    Style 字段序见 `_STYLE_FORMAT`：2=Fontsize，19/20=MarginL/R；可用宽度是 PlayResX
    减左右边距。超出这个宽度时 libass 不换行，而是整行居中铺出去、两端被画框切掉
    （实测见 test_ass_burn）——所以这是硬边界，不是排版偏好。
    """
    ass = build_ass([{"start": 0, "end": 2, "text": "探针"}], preset)
    play_res_x = next(
        int(line.split(":", 1)[1]) for line in ass.splitlines() if line.startswith("PlayResX")
    )
    size = _style_field_int(ass, 2)
    usable = play_res_x - _style_field_int(ass, 19) - _style_field_int(ass, 20)
    return size, usable


def _advance(size: int) -> int:
    """一个全角字的步进像素，用生产那份常数算。

    常数本身不在这里验（它由 test_ass_burn 在真机墨迹上钉死），这里只验**上下游是否
    同源**：头部写的字号/边距变了而上限没跟着变，就会在这里红。
    """
    return size * ass_generator._GLYPH_ADVANCE_PERCENT // 100


@pytest.mark.parametrize("preset_id", ["calm-narrative", "conflict-impact", "karaoke-pop"])
def test_line_cap_fits_one_line_of_fullwidth_glyphs(preset_id: str) -> None:
    """拆出来的每条字幕必须**一行放得下**，并且不超业主立案②的「≤16 字读得完」。"""
    preset = presets.get_preset(preset_id)
    size, usable = _line_metrics(preset)
    cap = ass_generator.line_char_cap(preset)
    assert cap <= 16, f"{preset_id}: 一条字幕 {cap} 字，超出立案②的 ≤16 字分段规格"
    assert cap * _advance(size) <= usable, (
        f"{preset_id}: 上限 {cap} 字 × {_advance(size)}px = {cap * _advance(size)}px > {usable}px"
    )
    assert split_subtitle_text(_NO_PUNCT_RUN, cap)[0]


def test_cap_follows_the_header_geometry_not_a_hardcoded_number() -> None:
    """上限是几何推出来的：字号小到时「读得完」先到顶，字号大时几何接管。"""
    assert ass_generator.line_char_cap({"font": {"name": "X", "size": 40}}) == 16
    big = {"font": {"name": "X", "size": 96}}
    assert ass_generator.line_char_cap(big) < 16, "字号 96 没有收紧上限：写死的还是那个 16"
    # 预设没给字号时走头部自己的默认字号：断言用同一次渲染读出的几何，不抄常数
    default_size, default_usable = _line_metrics({})
    assert ass_generator.line_char_cap({}) * _advance(default_size) <= default_usable


def test_cap_is_the_tightest_number_the_header_geometry_allows() -> None:
    """上限正好贴着 ASS 头部那套几何：多一字放不下、少一字是浪费。

    两侧都夹住，才逼得着上限去读头部——它自带一份边距的话，这里必红。
    """
    for size in (96, 120):
        preset = {"font": {"name": "X", "size": size}}
        header_size, usable = _line_metrics(preset)
        cap = ass_generator.line_char_cap(preset)
        assert header_size == size
        assert cap * _advance(header_size) <= usable, f"字号 {size}：{cap} 字放不进 {usable}px"
        assert (cap + 1) * _advance(header_size) > usable, (
            f"字号 {size}：上限 {cap} 比头部允许的更小——它没在读头部那套几何"
        )


def test_split_never_exceeds_cap_and_never_loses_a_char() -> None:
    """两条全局性质：任一行不超上限；拆完拼回去等于原文（空白除外）。"""
    for max_len in (6, 10, 16):
        for text in (
            _NO_PUNCT_RUN,
            _PUNCTUATED,
            "一句话",
            "带，标点也，很长" * 8,
            "  前后空白会被去掉  ",
            "混排 english 单词 和中文，还有数字 1234567890",
        ):
            chunks = split_subtitle_text(text, max_len)
            assert chunks, f"{text!r} 拆成了空列表"
            assert all(len(chunk) <= max_len for chunk in chunks), f"{max_len} 被超过：{chunks}"
            assert _stripped("".join(chunks)) == _stripped(text), f"丢字了：{chunks}"


def test_split_breaks_at_punctuation_before_hard_cutting() -> None:
    """有标点可断时**不得**出现句中硬切：每条都应是完整语义单元。"""
    chunks = split_subtitle_text(_PUNCTUATED, 16)
    assert chunks == ["她本以为嫁了个老实人，", "谁知道新婚夜他锁上了门。", "门外传来婆婆的笑声！"]


def test_split_hard_cuts_a_run_without_punctuation() -> None:
    """整段无标点（长旁白常见）：只能按上限硬切，且切点均匀不残段。"""
    chunks = split_subtitle_text(_NO_PUNCT_RUN, 10)
    assert chunks == [_NO_PUNCT_RUN[i : i + 10] for i in range(0, len(_NO_PUNCT_RUN), 10)]
    assert all(len(chunk) == 10 for chunk in chunks[:-1])


def test_split_remerges_short_pieces() -> None:
    """碎段回并：前一行还有位置就不能另起一行（否则字幕会闪成一片碎片）。"""
    chunks = split_subtitle_text("好，真的，太好了，没错", 16)
    assert chunks == ["好，真的，太好了，没错"], f"短句被留成了独立行：{chunks}"


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_split_on_blank_input_is_nonempty(text: str) -> None:
    """空白输入不能返回 []：调用方按「至少一条」分配时长，空列表即除零。"""
    assert split_subtitle_text(text, 12) == [""]


def test_long_narration_becomes_multiple_ass_events() -> None:
    """拆行结果喂进 build_ass 必须变成**多条**事件——一条都不超一行宽度。

    这条是「拆了但没烧进去」的探测器：只测 split 的话，preset/事件层断了也不会红。
    """
    preset = presets.get_preset("karaoke-pop")
    cap = ass_generator.line_char_cap(preset)
    chunks = split_subtitle_text(_NO_PUNCT_RUN, cap)
    assert len(chunks) > 1, "用例已失效：这段旁白不再触发拆行"
    ass = build_ass(
        [{"start": i * 1.5, "end": i * 1.5 + 1.5, "text": chunk} for i, chunk in enumerate(chunks)],
        preset,
    )
    assert ass.count("Dialogue:") == len(chunks)
    size, usable = _line_metrics(preset)
    for line in ass.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        text = _stripped(_event_text(line))
        assert len(text) <= cap, f"这条字幕超上限：{text!r}"
        assert len(text) * _advance(size) <= usable, f"这条字幕一行放不下：{text!r}"


def _event_text(ass_line: str) -> str:
    """Dialogue 行的纯字幕文字：剥掉 `{...}` 覆盖标签（含 karaoke 的 `\\k` 序列）。"""
    return re.sub(r"\{[^{}]*\}", "", ass_line.split(",", 9)[9])


@pytest.mark.parametrize("preset_id", ["calm-narrative", "conflict-impact", "karaoke-pop"])
def test_build_ass_refuses_a_line_wider_than_the_frame(preset_id: str) -> None:
    """不经过拆行直接喂 build_ass 的调用方（未来的预览/新出口）必须**失败**，不是烧出一条
    首尾被画框切掉的字幕。

    这正是业主立案②的形状：`split_subtitle_text` 只在 burn_subtitle 里被调一次，那一
    层断了这条就没人接。边界两侧都测：cap 字放行，cap+1 字拒绝。
    """
    preset = presets.get_preset(preset_id)
    cap = ass_generator.line_char_cap(preset)
    build_ass([{"start": 0, "end": 2, "text": _NO_PUNCT_RUN[:cap]}], preset)
    with pytest.raises(ValueError, match="单行上限"):
        build_ass([{"start": 0, "end": 2, "text": _NO_PUNCT_RUN[: cap + 1]}], preset)


def test_split_output_always_survives_the_build_ass_guard() -> None:
    """拆行与 build_ass 的门禁必须互相咬合：拆出来的每条都不能触发上面那道拒绝。"""
    for preset_id in ("calm-narrative", "conflict-impact", "karaoke-pop"):
        preset = presets.get_preset(preset_id)
        cap = ass_generator.line_char_cap(preset)
        chunks = split_subtitle_text(_PUNCTUATED + _NO_PUNCT_RUN, cap)
        assert len(chunks) > 1, "用例已失效：这段文案不再触发拆行"
        build_ass(
            [{"start": i, "end": i + 1, "text": chunk} for i, chunk in enumerate(chunks)],
            preset,
        )

