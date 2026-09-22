"""ASS 字幕生成器（原案 6A）：预设四维度 → ASS 文件，供 FFmpeg `ass` 滤镜烧录。
"""

from __future__ import annotations

import re
from typing import Any

from dramaclip.engines.subtitle import caption_font
from dramaclip.engines.subtitle.emotion_matcher import match_emotion

_ALIGNMENT = {"bottom_bar": 2, "center_single": 5, "center_multi": 5, "top_title": 8}
_DEFAULT_LAYOUT = "bottom_bar"
_EFFECT_TAGS = {
    "none": "",
    "shake": "\\fscx105\\fscy105",
    "scale_glow": "\\fscx112\\fscy112\\bord4",
}

# ASS 头部与拆行上限共用这一组几何：两处各写一份的话，改了字号/边距那一侧不会有人
# 提醒另一侧，一行字幕就会超出演示区（业主立案②的实测形状：整行向两侧溢出、首尾被画框切掉）。
_PLAY_RES_X = 1080
_PLAY_RES_Y = 1920
_SIDE_MARGIN_PX = 40
_DEFAULT_FONT_SIZE = 64
# 一个全角字的步进宽度对 ASS 字号的百分比。随包字面（resources/fonts 那份 Noto Sans SC
# Regular）在 bundled ffmpeg 8.1.1 上逐字量得 0.6906 em——它等于 unitsPerEm 1000 ÷
# (ascender 1160 + descender 288)，即 libass 经 DirectWrite 把 ASS 字号换算成字身的那
# 一步。常数由 test_ass_burn 在同一份字面上重标，换字体不改这里必红。
_GLYPH_ADVANCE_PERCENT = 69
# 一条字幕放几个字读得完：业主立案②的分段规格，与「放得下」取更紧的一个
_CAPTION_PACE_CHARS = 16


def _layout_of(preset: dict[str, Any], key: str = "default") -> str:
    """取预设的布局名（default / climax 两档）；缺档回退贴底。"""
    layout_map = preset.get("dimensions", {}).get("layout", {})
    return str(layout_map.get(key, _DEFAULT_LAYOUT))


def _placement(layout: str, preset_margin_v: int) -> tuple[int, int]:
    """布局名 → (ASS 九宫格对齐, MarginV)。

    居中档（5）下 MarginV 不参与纵向定位，给 0：沿用贴底那档的小留白会把整行字
    沉到画面底缘之外（业主截图「字幕下半被裁」即此形状）。
    """
    alignment = _ALIGNMENT.get(layout, _ALIGNMENT[_DEFAULT_LAYOUT])
    return (alignment, 0) if alignment == 5 else (alignment, preset_margin_v)


def _margin_v(preset: dict[str, Any]) -> int:
    return int(preset.get("font", {}).get("margin_v", 80))


def _font_size(preset: dict[str, Any]) -> int:
    return int(preset.get("font", {}).get("size", _DEFAULT_FONT_SIZE))


def line_char_cap(preset: dict[str, Any]) -> int:
    """单行字幕最多放几个字：「读得完」与「放得下」取更紧的那个。

    放得下 = 演示区宽度 ÷ 每字步进，步进按随包字面量出来（见 `_GLYPH_ADVANCE_PERCENT`
    的来历）。超出后 libass **不会换行**：整行照样居中铺出去，两端被画框切掉——实测
    17 字时墨迹占到 x=[25,1053]，越出 40/1040 演示区。三套内置预设的字号（64/72/80）
    几何档各是 22/20/17 字，都不比「读得完」更紧；字号 96 起才轮到几何档接管（实测
    上限收到 15 字，16 字就越界）。`max(1, ...)` 只是硬切循环的终止保证，不是承诺。
    """
    usable = _PLAY_RES_X - 2 * _SIDE_MARGIN_PX
    advance = _font_size(preset) * _GLYPH_ADVANCE_PERCENT // 100
    return min(_CAPTION_PACE_CHARS, max(1, usable // advance))


_STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour,"
    " BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle,"
    " BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
)
_EVENT_FORMAT = "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"


def _header(preset: dict[str, Any]) -> str:
    font = preset.get("font", {})
    alignment, margin_v = _placement(_layout_of(preset), _margin_v(preset))
    # 族名不接受预设指定：预设能换字号/边距，但字面是随包资产，拆行上限按它标定
    style = (
        f"Style: DC,{caption_font.caption_font().family},{_font_size(preset)},"
        f"&H00FFFFFF,&H00FFFFFF,&H00000000,&H7F000000,"
        f"{-1 if font.get('bold', False) else 0},0,0,0,100,100,0,0,1,"
        f"{int(font.get('outline_width', 3))},{int(font.get('shadow', 1))},{alignment},"
        f"{_SIDE_MARGIN_PX},{_SIDE_MARGIN_PX},{margin_v},1"
    )
    return "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {_PLAY_RES_X}",
            f"PlayResY: {_PLAY_RES_Y}",
            "WrapStyle: 0",
            "",
            "[V4+ Styles]",
            _STYLE_FORMAT,
            style,
            "",
            "[Events]",
            _EVENT_FORMAT,
        ]
    )


def _ass_time(seconds: float) -> str:
    """秒 → ASS 时间 H:MM:SS.CC。"""
    total = max(seconds, 0.0)
    hours = int(total // 3600)
    minutes = int((total % 3600) // 60)
    secs = total % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _color_override(style_def: dict[str, Any]) -> str:
    """情绪样式的颜色 override 串（\\c 主色 + \\3c 描边）——整行与 span 区间共用同一形状。

    span 刻意**不带**效果标签（shake/scale_glow 的 \\fscx）：那是缩放变换，内联插进
    行中会持续到行尾且回底色时无法撤销，一行字会一半大一倍。花字 span 只做颜色。
    """
    primary = str(style_def.get("primary", "&H00FFFFFF"))
    outline_color = str(style_def.get("outline", "&H00000000"))
    return f"\\c{primary}\\3c{outline_color}"


def _span_body(
    text: str,
    spans: list[Any],
    base_overrides: str,
    base_colors: str,
    emotion_styles: dict[str, Any],
) -> str:
    """按字符区间拼 span 化的行体：区间前插对应情绪颜色，区间后回插整行底色。

    坏区间（非三元组/坐标非整数/空区间/倒序/越界）逐个丢弃不 raise：花字是增益，
    一条脏数据不能把整段渲染炸掉。与底色同色的 span 不插标签，所以「span 恰好
    覆盖整行且情绪与行级一致」时输出与不给 span 逐字节相同。重叠区间先到者得。
    """
    valid: list[tuple[int, int, str]] = []
    for span in spans:
        if not isinstance(span, tuple) or len(span) != 3:
            continue
        start_raw, end_raw, label = span
        if not isinstance(start_raw, int) or not isinstance(end_raw, int):
            continue
        start = max(start_raw, 0)
        end = min(end_raw, len(text))
        if start >= end or not str(label):
            continue
        valid.append((start, end, str(label)))
    valid.sort()
    pieces: list[str] = [f"{{{base_overrides}}}"]
    cursor = 0
    active = base_colors  # 行首整段 override 已含底色，颜色状态从底色起算
    for start, end, label in valid:
        if start < cursor:
            continue
        emotion = match_emotion("", label)  # 与整行同一套标签归一化
        style_def = emotion_styles.get(emotion) or emotion_styles.get("default") or {}
        override = _color_override(style_def)
        if start > cursor:
            if active != base_colors:
                pieces.append(f"{{{base_colors}}}")
                active = base_colors
            pieces.append(_escape(text[cursor:start]))
        if override != active:
            pieces.append(f"{{{override}}}")
            active = override
        pieces.append(_escape(text[start:end]))
        cursor = end
    if cursor < len(text):
        if active != base_colors:
            # 回底色：不回插的话 span 之后所有字都染着区间颜色
            pieces.append(f"{{{base_colors}}}")
        pieces.append(_escape(text[cursor:]))
    return "".join(pieces)


def _event_line(line: dict[str, Any], preset: dict[str, Any]) -> str | None:
    text = str(line.get("text", "")).strip()
    if not text:
        return None
    cap = line_char_cap(preset)
    if len(text) > cap:
        # 超上限的行不会换行，只会居中后向两侧溢出、首尾被画框切掉（实测）——那是观众
        # 看得见的残缺，按「改所见所闻的一律失败不出片」的规矩不能默默烧出去。
        raise ValueError(f"字幕行超出单行上限 {cap} 字（实得 {len(text)} 字）：{text[:24]}…")

    dimensions = preset.get("dimensions", {})
    animation = dimensions.get("animation", {})
    layout_map = dimensions.get("layout", {})
    emotion_styles = dimensions.get("emotion_style", {})
    fade_ms = int(animation.get("fade_ms", 250))
    entrance = str(animation.get("entrance", "fade"))

    emotion = match_emotion(text, line.get("emotion_label"))
    style_def = emotion_styles.get(emotion) or emotion_styles.get("default") or {}
    primary = str(style_def.get("primary", "&H00FFFFFF"))
    outline_color = str(style_def.get("outline", "&H00000000"))
    effect = _EFFECT_TAGS.get(str(style_def.get("effect", "none")), "")

    layout_key = (
        "climax" if emotion in ("anger", "triumph") and "climax" in layout_map else "default"
    )
    alignment, margin_v = _placement(_layout_of(preset, layout_key), _margin_v(preset))

    rhythm = str(dimensions.get("rhythm", {}).get("type", "whole_line"))
    duration_s = float(line["end"]) - float(line["start"])
    # \an 逐行覆盖 Style 对齐：同一条片里 default 与 climax 两种布局会混排
    tags = [f"\\an{alignment}", f"\\fad({fade_ms},{fade_ms})"]
    if entrance == "bounce":
        tags.append("\\t(0,180,\\fscx115\\fscy115)\\t(180,320,\\fscx100\\fscy100)")
    if effect:
        tags.append(effect)
    colors = f"\\c{primary}\\3c{outline_color}"
    tags.append(colors)

    start = _ass_time(float(line["start"]))
    end = _ass_time(float(line["end"]))
    overrides = "".join(tags)
    if rhythm == "karaoke":
        # span 与逐字 \k 互斥：karaoke 每个字自带一段 override，再插区间颜色会互相
        # 覆盖出不可预测的形状——该路径下忽略 span（不给时行为本就逐字节一致）。
        body = _karaoke_body(text, duration_s, overrides, primary)
        return _event_row(start, end, margin_v, body)
    spans = line.get("span_emotions")
    if spans:
        body = _span_body(text, list(spans), overrides, colors, emotion_styles)
        return _event_row(start, end, margin_v, body)
    return _event_row(start, end, margin_v, f"{{{overrides}}}{_escape(text)}")


def _event_row(start: str, end: str, margin_v: int, body: str) -> str:
    """按 `_EVENT_FORMAT` 拼一条 Dialogue：字段用 join，逗号数不可能多写。

    字面量拼接时多一个逗号，libass 会把那一位当成文本开头的字面量**画**出来——
    实测（bundled ffmpeg 8.1.1，同一份生产 ASS 只改这个逗号）：conflict-impact
    「第一行」墨迹 3669→3747 像素、横向占据 458–620→451–628；karaoke-pop 4269→4403
    像素。即字幕前面挂一个逗号、整行重新居中。这组数今天仍由 test_ass_burn 在随包字面
    上重量，字面变了数量级不变——保护的是同一件事。
    """
    fields = ["0", start, end, "DC", "", "0", "0", str(margin_v), "", body]
    return f"Dialogue: {','.join(fields)}"


def _karaoke_body(text: str, duration_s: float, overrides: str, primary: str) -> str:
    """卡拉OK逐字高亮：ASS \\k 标签（厘秒），每字均分时长。
    """
    chars = [ch for ch in text if not ch.isspace()]
    if not chars:
        return "{" + overrides + "}" + _escape(text)
    per_cs = max(1, int(duration_s * 100 / len(chars)))
    parts = ["{" + overrides + f"\\1c{primary}\\2c&H5A5A5A}}"]
    for ch in chars:
        parts.append(f"{{\\k{per_cs}}}{_escape(ch)}")
    return "".join(parts)


_PUNCT_SPLIT = re.compile(r"(?<=[，。！？；：、…——])")

# 行尾不留句读（业主立案②的「标点清理」）。`_PUNCT_SPLIT` 在标点**之后**断句，所以每条
# 字幕都拖着自己那句的句号/逗号——短视频字幕的通行做法是行尾不放这些，它们只是排版噪声。
# ？！ 不在这里：它们承载的是语气（"他凭什么？"去掉问号就变成另一句话），必须留。
# 破折号「——」与省略号「…」按字符 rstrip，成对/连写的都能一次扫掉。
_TRAILING_MARKS = "，。、；：…——,.;:"
# 对 export 侧公开：原声台词按词组拼行时沿用同一套「行尾不留句读」的规矩
TRAILING_MARKS = _TRAILING_MARKS


def split_subtitle_text(text: str, max_len: int) -> list[str]:
    """长解说文案拆成字幕级短句：标点优先断句，超长句硬切，短段回并，行尾句读清理。

    `max_len` 没有默认值：能放几个字只取决于用哪套预设烧（`line_char_cap`），写死一个
    数就是业主立案②的形状——「拆了，但每条照样放不下」。
    """
    pieces: list[str] = []
    for sentence in _PUNCT_SPLIT.split(text.strip()):
        sentence = sentence.strip()
        if not sentence:
            continue
        while len(sentence) > max_len:
            pieces.append(sentence[:max_len])
            sentence = sentence[max_len:]
        if sentence:
            pieces.append(sentence)
    merged: list[str] = []
    for piece in pieces:
        if merged and len(merged[-1]) + len(piece) <= max_len:
            merged[-1] += piece
        else:
            merged.append(piece)
    # 清理必须在**回并之后**：回并把 "好，" + "真的" 拼成一行时，那个逗号从行尾挪到了
    # 行中，是句子的一部分。挪到回并之前清，就把该留的标点一起删了（变异实测会红
    # `test_remerged_commas_survive_the_cleanup`）。
    cleaned = [piece.rstrip(_TRAILING_MARKS) for piece in merged]
    # 整行只剩标点的（文案以「……」收尾就会产出这种行）留不得：0 字行在调用方按字数
    # 比例分时长时是除零的来源，也不能替自己占一格时间轴。
    return [piece for piece in cleaned if piece] or [""]


def build_ass(lines: list[dict[str, Any]], preset: dict[str, Any]) -> str:
    """生成 ASS 字幕全文。
    """
    events = [event for line in lines if (event := _event_line(line, preset)) is not None]
    return "\n".join([_header(preset), *events]) + "\n"
