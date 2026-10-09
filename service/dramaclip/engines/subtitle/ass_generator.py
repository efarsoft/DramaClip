"""ASS 字幕生成器（原案 6A）：预设四维度 → ASS 文件，供 FFmpeg `ass` 滤镜烧录。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from dramaclip.engines.subtitle import caption_font
from dramaclip.engines.subtitle.emotion_matcher import match_emotion

# 居中档（center_single/center_multi）统一落底：字幕禁止居中遮画面
# （2026-10-08 业主裁决）。climax 的大字号/情绪色保留，位置进底部字幕带。
_ALIGNMENT = {"bottom_bar": 2, "center_single": 2, "center_multi": 2, "top_title": 8}
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


@dataclass(frozen=True)
class Canvas:
    """ASS 播放画布 = 实际出图尺寸：PlayRes、字号、边距、拆行上限都按它推导。

    基准是竖屏 (1080,1920)——预设字号/边距按它标定；画布变化时等比缩放，
    视觉占比不变，拆行上限的几何档随宽线性走（usable/advance 两头乘同一尺）。
    """

    x: int = _PLAY_RES_X
    y: int = _PLAY_RES_Y

    @property
    def scale(self) -> float:
        return self.x / _PLAY_RES_X

    def font_px(self, preset: dict[str, Any]) -> int:
        return max(1, round(_font_size(preset) * self.scale))

    @property
    def side_margin(self) -> int:
        return max(1, round(_SIDE_MARGIN_PX * self.scale))


def _layout_of(preset: dict[str, Any], key: str = "default") -> str:
    """取预设的布局名（default / climax 两档）；缺档回退贴底。"""
    layout_map = preset.get("dimensions", {}).get("layout", {})
    return str(layout_map.get(key, _DEFAULT_LAYOUT))


def _placement(
    layout: str,
    preset: dict[str, Any],
    source_band: tuple[float, float] | None = None,
    canvas: Canvas | None = None,
) -> tuple[int, int]:
    """布局名 → (ASS 九宫格对齐, MarginV)。

    居中档（5）下 MarginV 不参与纵向定位，给 0：沿用贴底那档的小留白会把整行字
    沉到画面底缘之外（业主截图「字幕下半被裁」即此形状）。

    带内压位只作用于 bottom_bar（\an2）：居中档 MarginV 本就无意义，top_title
    （\an8）的 MarginV 是距**顶**距离，底部源带与它不相干——两者零改动。
    """
    alignment = _ALIGNMENT.get(layout, _ALIGNMENT[_DEFAULT_LAYOUT])
    preset_margin_v = _margin_v(preset, canvas)
    if alignment == 2:
        font = canvas.font_px(preset) if canvas is not None else _font_size(preset)
        return (alignment, cover_band_margin_v(source_band, preset_margin_v, canvas, font))
    return (alignment, preset_margin_v)


def _margin_v(preset: dict[str, Any], canvas: Canvas | None = None) -> int:
    """预设 MarginV（基准 1080×1920 坐标）→ 实际画布坐标，纵向线性缩放。"""
    preset_value = int(preset.get("font", {}).get("margin_v", 80))
    # 只做坐标缩放；源带避让归 _placement 的贴底分支（它知道布局适不适用）
    return round(preset_value * (canvas.y / _PLAY_RES_Y)) if canvas is not None else preset_value


# ── A2 源硬字幕带压位（覆盖，不是避让：源带像素由编码端 delogo 擦掉，我们的字放回原位）──
#
# 业主立锁「硬字幕擦除不当核心」约束的是擦除那条线；这里是位置——短剧源片常自带
# 底部硬字幕，擦掉后把我们的字幕放回同一处，才是观众看竖屏短剧的阅读位置
# （2026-10-06 裁决「直接覆盖原始字幕」推翻早期「只抬到带顶之上」的避让语义）。
#
# 换算几何（单一真相，两处写死的数字都会在这里被测试钉住）：
# - PlayResY = 1920（本文件 `_PLAY_RES_Y`，头部唯一来源）；视频按 PlayRes 坐标渲染，
#   带/行框是「占画面高度比例」的归一化值，直接乘 PlayResY 就是像素，无需知道真实分辨率。
# - \an2（bottom_bar）下 MarginV = 字幕**盒底**距画面**底边**的像素数。
# - 目标 top 是距画面**顶**的比例，故目标中心距画面底 = (1 - center) × PlayResY。
# - 覆盖 ⇔ 我们的**墨迹中心**落在目标中心 ⇔ MarginV = (1 - center)×PlayResY - 墨迹锚距。
# - 下限 preset_margin_v：目标比预设字幕线还贴底时不往下挪（预设 80/90 只占画面底 ~4%）。
# - 封顶 PlayResY×2/3：目标探到画面中部属异常形状，不把字幕抬出演示区。
_MARGIN_CAP_RATIO = 2 / 3

# 超高「带」（>35% 画布高）是满幅文字背景误检——压位跟随它会悬空画面中部
# （2026-10-09 真机 16:9 片头字幕墙反馈），回退预设边距。覆盖闸取同一条线：
# 生成端在这里放弃承诺，闸就不追一个没做的承诺。
_BAND_GARBAGE_MAX_H = 0.35

# \an2 的 MarginV 锚的是字幕**盒底**，不是墨迹中心：随包字面（Noto Sans SC）的
# 一行的墨迹中心落在盒底上方 0.455 个字号处（ascent/descent 1160:288 与 CJK
# ideographic em box 合成，真机逐集量得）。旧实现按经验系数 font×1.9 造了个
# 幻影盒把它居中，墨迹因此系统性偏低 ~31px——「精准覆盖原有字幕」差的就是
# 这一段（2026-10-09 业主裁决 B 覆盖优先）。tests/engines/subtitle/test_band_cover.py
# 用实测数钉住这个常量，改字号模型不改这里必红。
_INK_CENTER_TO_ANCHOR = 0.455


def cover_band_margin_v(
    band: tuple[float, float] | tuple[int, int] | None,
    preset_margin_v: int,
    canvas: Canvas | None = None,
    font_px: int | None = None,
) -> int:
    """归一化目标矩形 → bottom_bar 布局的 MarginV（墨迹中心对齐矩形中心）。

    前置：编码端已对该带 delogo 擦除，源字幕文字已不可见——我们的字幕放回带内
    居中，是观众看竖屏短剧的字幕位置习惯（2026-10-06 业主裁决「直接覆盖原始字
    幕」，推翻 90004e4 的「只避让不遮挡」）。

    band 为 None（未探测/无硬字幕带/OCR 未装）→ 原样返回 preset_margin_v，
    降级不可见，生成的 ASS 与无带现状逐字节一致。
    band 两种形态：归一化分数（相对画面高），或画布像素区间 (top_px, bottom_px)
    ——后者供 16:9 源 letterbox 进 9:16 画布时的**内容锚定**换算（带分数是相对
    源画面高的，画布补黑后必须按内容区折算，见 export 端）。
    几何在**实际画布**坐标系里算（canvas.y，缺省基准 1920）：
    - 目标中心距画面底 = (1 - center) × res_y，center 为矩形上下沿中值；
      调用端优先给**采信行框的并集**（比整带紧，中心即台词墨迹中心），
      行框缺失才回退整带包络；
    - margin = 该中心 - _INK_CENTER_TO_ANCHOR × 字号（盒底锚点换算，见常量注释）；
    - 下限 preset_margin_v：源字比预设位置还贴底时不往下挪；
    - 封顶 PlayResY×2/3：目标探到画面中部属异常形状，不把字幕抬出演示区。
    """
    if band is None:
        return preset_margin_v
    res_y = canvas.y if canvas is not None else _PLAY_RES_Y
    top_px, bottom_px = float(band[0]), float(band[1])
    if top_px > 1 or bottom_px > 1:  # 画布像素带：直接用
        margin = res_y - bottom_px
        cap = int(res_y * _MARGIN_CAP_RATIO)
        return max(preset_margin_v, min(round(margin), cap))
    top = min(max(top_px, 0.0), 1.0)
    bottom = min(max(bottom_px, 0.0), 1.0)
    if bottom - top > _BAND_GARBAGE_MAX_H:
        # 满幅文字背景误检：跟随它会悬空画面中部，回退预设边距（见常量注释）
        return preset_margin_v
    center = (top + bottom) / 2
    font = font_px if font_px else _DEFAULT_FONT_SIZE
    margin = round((1.0 - center) * res_y - _INK_CENTER_TO_ANCHOR * font)
    cap = int(res_y * _MARGIN_CAP_RATIO)
    return max(preset_margin_v, min(margin, cap))


# ── 出片前覆盖性静态闸（业主裁决④：字幕盖在源台词带上，漂了就不出片）──
#
# 「我需要的是字幕精准覆盖原有字幕，而不是到处乱跑」——生成端自洽不代表落点对：
# 接线漏传 source_band、Dialogue 字段索引漂了、`\an` 与 MarginV 的语义被改坏，
# ASS 照样能生成、烧出来却贴底或悬空。闸读**最终 ASS 文本**独立反解落点，编码前
# raise：位置错是观众一眼看得见的缺陷，不出片优于出错片（质量优先，无降级）。
#
# 判的是**中心**，不是「墨迹装得下带」（2026-10-09 真机：《大明》10 集拦 8 集）：
# 生成端的承诺是「墨迹中心对齐带心」（见 `cover_band_margin_v`），包含式判据却要求
# 墨迹高 ≤ 带高——墨迹高 = 字号÷画布高，是个与 MarginV 无关的常量（竖屏 72/1920≈0.037，
# 横屏 128/1080≈0.119），带高却是 OCR 实测值。源字幕比我们的字小是常态，于是「任何
# MarginV 都不成立」的空判据把完全居中的落位当缺陷挡掉。业主口径：「保障字幕始终在原
# 视频字幕位置/区域，能完全覆盖就完全覆盖，不能覆盖不用太在意」——区域一致即中心一致，
# 尺寸差不是缺陷、也不该是挡片理由。
# 事后画面侧度量（exporter/selfcheck.check_caption_placement）同向判中心，只在容差上更松：
# 那边读数来自成片 OCR、有噪声，这边读的是自己刚写下的 ASS。两个数是两种测量噪声预算，
# 不是同一含义的第二处真相源——别把它们并成一个常量。
# 容差 ≈19px@1920 / 11px@1080：吃下 MarginV 取整与字体模型误差，不容错位一行。
_PLACEMENT_TOL_RATIO = 0.01
_PLACEMENT_MIN_CENTER_RATIO = 0.5  # 承诺区是画面下半；上半的带归 2/3 封顶管辖区
# 墨迹高度上界：CJK 方块字一行不超过一个字号高。判定只用中心（这个上界在中心式判据里
# 两侧对称、自行抵消），留着是为了让报错文案里的区间和烧出来的字形对得上。
_INK_HALF_TO_FONT = 0.5

_PLAY_RES_Y_RE = re.compile(r"^PlayResY:[ \t]*(\d+)", re.MULTILINE)
_AN_OVERRIDE_RE = re.compile(r"\\an([1-9])")
_FS_OVERRIDE_RE = re.compile(r"\\fs(\d+)")
_TAG_RE = re.compile(r"\{[^}]*\}")


def _ink_center(margin_v: float, font_px: float, res_y: float) -> float:
    """`\an2` 一行的墨迹纵向中心（占画面高的比例，自顶向下）——承诺的落点就是它。

    MarginV 锚的是**盒底**距画面底，随包字面的一行墨迹中心在锚点上方
    `_INK_CENTER_TO_ANCHOR` 个字号处（真机标定，见常量注释）。
    """
    return 1.0 - (margin_v + _INK_CENTER_TO_ANCHOR * font_px) / res_y


def _ink_interval(margin_v: float, font_px: float, res_y: float) -> tuple[float, float]:
    """`\an2` 的一行 → 墨迹纵向区间（占画面高的比例，自顶向下）。

    中心即 `_ink_center`，上下沿各按 `_INK_HALF_TO_FONT` 个字号铺开。
    """
    center = _ink_center(margin_v, font_px, res_y)
    half = _INK_HALF_TO_FONT * font_px / res_y
    return (center - half, center + half)


def coverage_promised(band: tuple[float, float] | None) -> bool:
    """生成端对这块源带**承诺覆盖**吗——两种放弃承诺的形状在这里一次说清。

    「承诺」的定义只能有一处真相：出片前的静态闸和成片后的画面侧度量都读它，
    否则「闸放过的形状被度量判红」这种自相矛盾迟早会出现。

    False 的两种（`cover_band_margin_v` 在这两处都回退预设边距）：
    - 带高 > `_BAND_GARBAGE_MAX_H`：满幅文字背景误检，跟它走字幕悬空画面中部；
    - 带心在画面下半之外（< 0.5）：抬进上部归 `_MARGIN_CAP_RATIO` 封顶管辖区，
      不属于「把字放回原字幕位」的承诺。
    """
    if band is None:
        return False
    top, bottom = float(band[0]), float(band[1])
    return (
        bottom - top <= _BAND_GARBAGE_MAX_H
        and (top + bottom) / 2 >= _PLACEMENT_MIN_CENTER_RATIO
    )


def placement_violations(
    ass_text: str,
    band: tuple[float, float] | None,
    preset_margin_v: int,
) -> list[str]:
    """生成的 ASS 是否把每行底部字幕的**中心**放回源台词带；返回违规描述（空表=通过）。

    判据与 `cover_band_margin_v` 独立：从最终文本反解 PlayResY、Style 字号/对齐/
    边距，逐行取 `\\an`、`\\fs` 覆盖与 MarginV 字段——所以「公式自洽但接线漂了」才
    拦得住（拿生成端的中间量对生成端的输出，等于没测）。判中心而非判「装得下」：
    理由见上方常量段的真机记录。

    不判的两种形状（误报即挡片）：
    - `coverage_promised` 为假 → 无带/满幅误检带/上半带，生成端本就没承诺覆盖；
    - 带心已在预设墨迹中心以下 → `cover_band_margin_v` 的下限钳生效，生成端刻意不往下挪。
    只判 `\an2` 的行：`\an8`（top_title）的 MarginV 是距**顶**距离，与底部带不相干。
    """
    if band is None or not coverage_promised(band):
        return []  # `band is None` 只为把类型收到二元组，判据在 coverage_promised 里
    res_y_match = _PLAY_RES_Y_RE.search(ass_text)
    style = next((line for line in ass_text.splitlines() if line.startswith("Style:")), "")
    fields = style.split(",")
    if res_y_match is None or len(fields) < 22:
        return []  # 不是本模块生成的 ASS 形状，没有可反解的基准
    res_y = float(res_y_match.group(1))
    top, bottom = float(band[0]), float(band[1])
    band_center = (top + bottom) / 2
    font_px = float(fields[2])
    if band_center >= _ink_center(preset_margin_v, font_px, res_y):
        return []  # 带心贴在预设墨迹中心以下：往下挪被下限钳挡住，不是承诺
    base_align = int(fields[18])
    base_margin = int(fields[21])
    violations: list[str] = []
    for line in ass_text.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) < 10:
            continue
        text = parts[9]
        align_match = _AN_OVERRIDE_RE.search(text)
        if (int(align_match.group(1)) if align_match else base_align) != 2:
            continue
        # MarginV 字段 0 在 ASS 里是「跟随 Style」的缺省语义
        margin_v = float(parts[7]) or base_margin
        fs_match = _FS_OVERRIDE_RE.search(text)
        ink_top, ink_bottom = _ink_interval(
            margin_v, float(fs_match.group(1)) if fs_match else font_px, res_y
        )
        ink_center = (ink_top + ink_bottom) / 2
        offset = abs(ink_center - band_center)
        if offset > _PLACEMENT_TOL_RATIO:
            violations.append(
                f"「{_TAG_RE.sub('', text).strip()[:12]}」落点中心 {ink_center:.3f}"
                f" 偏离源台词带中心 {band_center:.3f}（带 {top:.3f}–{bottom:.3f}，"
                f"墨迹 {ink_top:.3f}–{ink_bottom:.3f}）偏移 {offset:.3f}"
                f" > 容差 ±{_PLACEMENT_TOL_RATIO:.2f}"
            )
    return violations


def _font_size(preset: dict[str, Any]) -> int:
    return int(preset.get("font", {}).get("size", _DEFAULT_FONT_SIZE))


def line_char_cap(preset: dict[str, Any], canvas: Canvas | None = None) -> int:
    """单行字幕最多放几个字：「读得完」与「放得下」取更紧的那个。

    放得下 = 演示区宽度 ÷ 每字步进，步进按随包字面量出来（见 `_GLYPH_ADVANCE_PERCENT`
    的来历）。超出后 libass **不会换行**：整行照样居中铺出去，两端被画框切掉——实测
    17 字时墨迹占到 x=[25,1053]，越出 40/1040 演示区。三套内置预设的字号（64/72/80）
    几何档各是 22/20/17 字，都不比「读得完」更紧；字号 96 起才轮到几何档接管（实测
    上限收到 15 字，16 字就越界）。`max(1, ...)` 只是硬切循环的终止保证，不是承诺。
    画布非基准时宽/字号/边距同尺缩放，可容纳字数不变——视觉占比恒定。
    """
    res_x = canvas.x if canvas is not None else _PLAY_RES_X
    margin = canvas.side_margin if canvas is not None else _SIDE_MARGIN_PX
    font_px = canvas.font_px(preset) if canvas is not None else _font_size(preset)
    usable = res_x - 2 * margin
    advance = font_px * _GLYPH_ADVANCE_PERCENT // 100
    return min(_CAPTION_PACE_CHARS, max(1, usable // advance))


_STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour,"
    " BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle,"
    " BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
)
_EVENT_FORMAT = "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"


def _header(
    preset: dict[str, Any],
    source_band: tuple[float, float] | None = None,
    canvas: Canvas | None = None,
) -> str:
    font = preset.get("font", {})
    alignment, margin_v = _placement(_layout_of(preset), preset, source_band, canvas)
    res_x = canvas.x if canvas is not None else _PLAY_RES_X
    res_y = canvas.y if canvas is not None else _PLAY_RES_Y
    font_px = canvas.font_px(preset) if canvas is not None else _font_size(preset)
    side = canvas.side_margin if canvas is not None else _SIDE_MARGIN_PX
    # 族名不接受预设指定：预设能换字号/边距，但字面是随包资产，拆行上限按它标定
    style = (
        f"Style: DC,{caption_font.caption_font().family},{font_px},"
        f"&H00FFFFFF,&H00FFFFFF,&H00000000,&H7F000000,"
        f"{-1 if font.get('bold', False) else 0},0,0,0,100,100,0,0,1,"
        f"{int(font.get('outline_width', 3))},{int(font.get('shadow', 1))},{alignment},"
        f"{side},{side},{margin_v},1"
    )
    return "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {res_x}",
            f"PlayResY: {res_y}",
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


def _event_line(
    line: dict[str, Any],
    preset: dict[str, Any],
    source_band: tuple[float, float] | None = None,
    canvas: Canvas | None = None,
) -> str | None:
    text = str(line.get("text", "")).strip()
    if not text:
        return None
    cap = line_char_cap(preset, canvas)
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
    alignment, margin_v = _placement(
        _layout_of(preset, layout_key), preset, source_band, canvas
    )

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


def build_ass(
    lines: list[dict[str, Any]],
    preset: dict[str, Any],
    *,
    source_band: tuple[float, float] | None = None,
    play_res: tuple[int, int] | None = None,
) -> str:
    """生成 ASS 字幕全文。

    `source_band`：要覆盖上去的源硬字幕带（归一化 (top, bottom)，编码端已对它
    delogo 擦除），来自 episode_analysis.subtitle_band（JSON 两元数组）。给了且形状
    可信时按带内压位定 MarginV（见 `cover_band_margin_v`）；None → 输出与不给时逐字
    节一致（降级不可见）。只影响 `\an2`：top_title（`\an8`）零改动。
    返回前过 `placement_violations` 覆盖闸：生成的落点中心不在这块带上 → raise ValueError
    （承诺在此作出，也在此核验；调用端漏不漏接线都拦得住）。
    `play_res`：实际出图画布（encoder.resolve_canvas 的结果）——PlayRes/字号/边距/
    拆行上限全部按它推导；缺省回基准竖屏（逐字节兼容旧输出）。
    """
    canvas = Canvas(*play_res) if play_res is not None else None
    events = [
        event
        for line in lines
        if (event := _event_line(line, preset, source_band, canvas)) is not None
    ]
    ass_text = "\n".join([_header(preset, source_band, canvas), *events]) + "\n"
    violations = placement_violations(ass_text, source_band, _margin_v(preset, canvas))
    if violations:
        raise ValueError("字幕覆盖闸：\n" + "\n".join(violations))
    return ass_text
