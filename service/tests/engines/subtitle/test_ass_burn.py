"""字幕烧录真机量：事件行的逗号数，与「一行放得下」在 libass 里的实际后果。

业主立案②（解说文案整段一条字幕超长）的最终裁决者是烧录时的 libass，不是我们写在
常数表里的数字。烧一帧、量墨迹，得到三件事：

1. `Dialogue` 多一个逗号，libass 会把多出来的那一位当成字幕文本**画**出来：
   `test_a_stray_comma_*` 实测墨迹 3669→3747 像素、整行重新居中。
2. 一行太长**不会被换行**，而是居中后向两侧溢出、被画框切掉：16 字在三档内置预设里
   都还在演示区内（最紧的 karaoke-pop 字号 80 墨迹到 x=1023），17 字即越到 x=1053。
3. 每字步进实测是 0.757–0.771 字号，不是「约等于字号」：所以内置三档的上限都由
   「读得完」（≤16 字）这一档决定，几何档要字号 81 以上才接管。把字号推到 96，
   上限自动收到 13 字，而 14 字真就越界——`test_a_bigger_font_*` 是这条链的实测凭据。
"""

from __future__ import annotations

import subprocess  # noqa: S404 - 参数为受控列表
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from dramaclip.engines.subtitle import ass_generator, caption_font, presets
from dramaclip.engines.subtitle.ass_generator import build_ass, line_char_cap, split_subtitle_text

_FFMPEG = Path(__file__).resolve().parents[4] / "resources" / "ffmpeg" / "ffmpeg.exe"
_BG = np.array([16, 16, 16], dtype=np.int16)  # color=0x101010
_RUN = "她怎么也想不到那个温声细语的男人会在新婚夜锁上房门转身就走"
# 演示区（ASS 头部的 MarginL/R 那对边距围出来的可用宽度），不是画框边缘
_SAFE_LEFT = 40
_SAFE_RIGHT = 1080 - 40 - 1


def _paint(tmp_path: Path, ass_text: str, name: str) -> np.ndarray:
    """把一份 ASS 烧到纯色底上，返回该帧像素矩阵（bundled ffmpeg + **随包字体**）。

    `-ss 0.7` 取的是淡入**之后**的一帧：预设都带 fad 标签，第 0 帧全透明，量不到墨。
    滤镜串走相对路径：encoder 的 `_escape_filter_path` 同样优先相对路径，盘符冒号在
    滤镜串里会被当成选项分隔符。`fontsdir` 用 encoder 生产那份同一构造的选项——量的
    必须是被烧出来的那个字面，否则这条门禁测的是系统里恰好装着的字体。
    """
    assert _FFMPEG.is_file(), f"缺 bundled ffmpeg：{_FFMPEG}"
    (tmp_path / f"{name}.ass").write_text(ass_text, encoding="utf-8")
    fontsdir = caption_font.fontsdir_option(caption_font.caption_font())
    subprocess.run(  # noqa: S603 - 受控参数
        [
            str(_FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=0x101010:s=1080x1920:d=2:r=25",
            "-vf", f"ass={name}.ass:{fontsdir}",
            "-ss", "0.7", "-frames:v", "1", f"{name}.png",
        ],
        cwd=str(tmp_path),
        check=True,
    )
    return np.asarray(Image.open(tmp_path / f"{name}.png").convert("RGB"), dtype=np.int16)


def _burn(tmp_path: Path, preset: dict[str, object], text: str, name: str) -> np.ndarray:
    return _paint(tmp_path, build_ass([{"start": 0, "end": 2, "text": text}], preset), name)


def _ink(frame: np.ndarray) -> np.ndarray:
    return np.abs(frame - _BG).max(axis=2) > 24


def _span(mask: np.ndarray) -> tuple[int, int, int]:
    """(墨迹左缘, 墨迹右缘, 纵向分带数)——分带数即 libass 实际排了几行。"""
    ys, xs = np.nonzero(mask)
    rows = np.flatnonzero(mask.any(axis=1))
    bands = 1 + int((np.diff(rows) > 4).sum()) if len(rows) else 0
    return int(xs.min()), int(xs.max()), bands


def _event(ass_text: str) -> str:
    return next(line for line in ass_text.splitlines() if line.startswith("Dialogue:"))


def _fields(ass_text: str) -> tuple[list[str], int]:
    """(事件行按 Format 声明的字段数切开, 字段数)——个数取自这份 ASS 自己的 Format 行。"""
    format_line = next(line for line in ass_text.splitlines() if line.startswith("Format: Layer"))
    declared = len(format_line[len("Format: ") :].split(","))
    event = _event(ass_text)[len("Dialogue: ") :]
    return event.split(",", declared - 1), declared


@pytest.mark.parametrize("preset_id", ["conflict-impact", "karaoke-pop"])
def test_event_text_field_has_no_stray_leading_comma(preset_id: str) -> None:
    """Text 字段（Format 声明的最后一位）不能以逗号开头。

    多一个逗号 = 字幕前面挂一个可见字形（下一条用例实测）。两条分支都测：
    `karaoke-pop` 走逐字高亮的 body，`conflict-impact` 走整行 body。
    """
    preset = presets.get_preset(preset_id)
    ass_text = build_ass([{"start": 0, "end": 2, "text": "第一行"}], preset)
    fields, declared = _fields(ass_text)
    assert len(fields) == declared, f"事件行只有 {len(fields)} 个字段，Format 声明 {declared} 个"
    assert not fields[-1].startswith(","), f"Text 字段以逗号开头：{fields[-1][:20]!r}"


@pytest.mark.parametrize("preset_id", ["conflict-impact", "karaoke-pop"])
def test_a_stray_comma_before_the_text_is_visible_ink(tmp_path: Path, preset_id: str) -> None:
    """上面那条结构断言不是在管闲事：多一个逗号，画面真的动了。

    变异形状直接从生产产物上长出来（`,,{` → `,,,{`）——一旦事件行形状变了、这里构造
    不出变异，就是断言自身失败，不会静默通过。
    """
    preset = presets.get_preset(preset_id)
    produced = build_ass([{"start": 0, "end": 2, "text": "第一行"}], preset)
    with_stray = produced.replace(",,{", ",,,{", 1)
    assert with_stray != produced, "构造不出「多一个逗号」的形状：事件行已变，本用例失效"

    clean = _ink(_paint(tmp_path, produced, "clean"))
    stray = _ink(_paint(tmp_path, with_stray, "stray"))
    assert int(stray.sum()) > int(clean.sum()), "多一个逗号却没多出墨迹：libass 行为变了"
    left_clean = int(np.flatnonzero(clean.any(axis=0))[0])
    left_stray = int(np.flatnonzero(stray.any(axis=0))[0])
    assert left_stray < left_clean, "多出来的墨迹不在字幕左侧：保护对象变了"


@pytest.mark.parametrize("preset_id", ["calm-narrative", "conflict-impact", "karaoke-pop"])
def test_a_line_at_the_cap_stays_inside_the_safe_area(tmp_path: Path, preset_id: str) -> None:
    """上限内的字幕：整条落在演示区内、且只有一行。

    这是 `line_char_cap` 的实测定义——不是「按字号算够用」，是烧出来不越界。
    """
    preset = presets.get_preset(preset_id)
    cap = line_char_cap(preset)
    line = split_subtitle_text(_RUN, cap)[0]
    assert len(line) == cap, "用例已失效：这段旁白不再触顶"
    left, right, bands = _span(_ink(_burn(tmp_path, preset, line, "capped")))
    assert bands == 1, f"{preset_id}: 上限 {cap} 字被排成了 {bands} 行"
    assert left >= _SAFE_LEFT and right <= _SAFE_RIGHT, (
        f"{preset_id}: 上限 {cap} 字烧出来是 x=[{left},{right}]，越出演示区"
        f"[{_SAFE_LEFT},{_SAFE_RIGHT}]"
    )


def _preset_at_size(preset_id: str, size: int) -> dict[str, Any]:
    """整套预设只换字号，并把节奏压回整行：整行走明文文本，才能做下面的加长变异。"""
    preset = presets.get_preset(preset_id)
    dimensions = {**preset["dimensions"], "rhythm": {"type": "whole_line"}}
    return {**preset, "font": {**preset["font"], "size": size}, "dimensions": dimensions}


def _one_char_longer(ass_text: str, cap: int) -> str:
    """从生产产物上长出「多一个字」的变异——`build_ass` 现在会直接拒绝超上限的行，
    越界那一帧只能这样量出来（与 `test_a_stray_comma_*` 同一套路）。"""
    mutated = ass_text.replace(_RUN[:cap], _RUN[: cap + 1], 1)
    assert mutated != ass_text, "构造不出「多一个字」的形状：事件行已变，本用例失效"
    return mutated


@pytest.mark.parametrize("preset_id", ["calm-narrative", "conflict-impact", "karaoke-pop"])
def test_a_bigger_font_tightens_the_cap_and_that_cap_is_the_edge(
    tmp_path: Path, preset_id: str
) -> None:
    """把字号推到 96：上限必须由几何档接管，且接管后的数正好是放得下的上限。

    这条同时钉住两件事——「上限跟着字号走」不是纸面推导（13 字在内、14 字越界），
    以及上一条不是空转：内置预设留了余量，是因为「读得完」那一档先到，不是因为几何
    那一档虚设。
    """
    preset = _preset_at_size(preset_id, 96)
    cap = line_char_cap(preset)
    assert cap < 16, f"字号 96 没有收紧上限（还是 {cap}）：几何档没接管"

    produced = build_ass([{"start": 0, "end": 2, "text": _RUN[:cap]}], preset)
    in_left, in_right, _ = _span(_ink(_paint(tmp_path, produced, "bigger_cap")))
    over = _paint(tmp_path, _one_char_longer(produced, cap), "bigger_next")
    out_left, out_right, _ = _span(_ink(over))
    assert in_left >= _SAFE_LEFT and in_right <= _SAFE_RIGHT, (
        f"{preset_id}: 字号 96 的上限 {cap} 字烧出来是 x=[{in_left},{in_right}]，越界了"
    )
    assert out_left < _SAFE_LEFT or out_right > _SAFE_RIGHT, (
        f"{preset_id}: {cap + 1} 字竟然没越界（x=[{out_left},{out_right}]），"
        "上限比真实需要更保守，保护对象需要重估"
    )


def _ass_only_style(ass_text: str, **overrides: object) -> str:
    """换掉样式行的 Fontname/Fontsize，其余字段一字不动地沿用生产产物。"""
    lines = ass_text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("Style:"):
            fields = line[len("Style: ") :].split(",")
            fields[1] = str(overrides["family"])
            fields[2] = str(overrides["size"])
            lines[index] = "Style: " + ",".join(fields)
    return "\n".join(lines) + "\n"


def test_the_advance_constant_is_the_bundled_face_measured_advance(tmp_path: Path) -> None:
    """拆行上限里那个「每字步进占字号百分之几十」必须是**随包字面**量出来的数。

    常数是这套几何唯一的经验输入：它一变，上限就跟着变，而越界只有烧出来才看得见。
    换字体（或换了字体没重标常数）都会在这里红——差的这一头就是真机越界的那一头。
    """
    size = 64
    head = build_ass([{"start": 0, "end": 2, "text": "她"}], {"font": {"size": size}})
    ass = _ass_only_style(head, family=caption_font.caption_font().family, size=size)
    short = _span(_ink(_paint(tmp_path, ass.replace("她", "她" * 8), "adv_short")))
    long_ = _span(_ink(_paint(tmp_path, ass.replace("她", "她" * 16), "adv_long")))
    assert short[2] == 1 and long_[2] == 1, "同一行被排成了多行：这份产物不再能量步进"
    advance = (long_[1] - long_[0] - (short[1] - short[0])) / 8
    model = size * ass_generator._GLYPH_ADVANCE_PERCENT / 100
    assert advance <= model + 1.0, (
        f"随包字面实测每字步进 {advance:.1f}px > 常数允许的 {model:.1f}px（+1px 取整余量）："
        "上限会放过放不下的行，正是业主立案②的越界形状"
    )
    assert advance > model - 4.0, (
        f"实测步进 {advance:.1f}px 远小于常数允许的 {model:.1f}px：上限白留了余量，重标它"
    )
