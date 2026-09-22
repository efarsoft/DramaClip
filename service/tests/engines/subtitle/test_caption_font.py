"""随包字幕字体：族名、拆行上限、渲染必须指同一份字面（业主立案 D）。

修复前的形状：ASS 样式里硬写 `Microsoft YaHei`，拆行上限的每字步进按雅黑的墨迹标定，
渲染端却不带字体目录——`fontsdir` 没给时 libass 按族名找系统字体，找不到就**静默**
换一个（实测：同一份 ASS 只要族名在本机落空，每字步进从 0.691em 变成 0.789em，
上限算出来的字数照样烧得下，只是字面已经不是我们标定过的那个）。雅黑不可再分发，
所以这条路在别的机器上必然走偏。这里的判据是：字面随包走，三处读同一份真相。
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.subtitle import caption_font
from dramaclip.engines.subtitle.ass_generator import build_ass
from dramaclip.infra.paths import resolve_resources_dir

REPO_ROOT = Path(__file__).resolve().parents[4]
FONTS_DIR = resolve_resources_dir() / "fonts"
# 系统字体不是随包资产：写进代码或预设里，等于把渲染交给自己管不着的东西
_SYSTEM_FAMILIES = ("Microsoft YaHei", "SimHei", "SimSun", "PingFang", "微软雅黑", "宋体", "黑体")


def _style_field(ass_text: str, index: int) -> str:
    line = next(line for line in ass_text.splitlines() if line.startswith("Style:"))
    return line[len("Style: ") :].split(",")[index]


def _fake_font(dir_path: Path, family: str) -> Path:
    """手搓一份只带 name 表的最小 sfnt：证明族名是从文件里读的，不是抄回来的常数。"""
    entries = b""
    strings = b""
    for name_id, value in ((1, family), (2, "Regular")):
        payload = value.encode("utf-16-be")
        entries += struct.pack(
            ">HHHHHH", 3, 1, 0x409, name_id, len(payload), len(strings)
        )
        strings += payload
    name_table = struct.pack(">HHH", 0, 2, 6 + len(entries)) + entries + strings
    table_dir = b"name\x00\x00\x00\x00" + struct.pack(">II", 28, len(name_table))
    path = dir_path / "probe.otf"
    path.parent.mkdir(parents=True, exist_ok=True)
    # sfnt 头：'OTTO' + 1 张表，后 6 字节（searchRange 等）全 0 也读得出 name 表
    path.write_bytes(struct.pack(">IHHHH", 0x4F54544F, 1, 0, 0, 0) + table_dir + name_table)
    return path


# --------------------------------------------------------------- 随包资产本体


def test_a_redistributable_font_ships_with_its_license() -> None:
    """字体与它的授权声明必须一起随包：只放字不放 OFL 文本等于没授权。"""
    faces = sorted(p for p in FONTS_DIR.iterdir() if p.suffix.lower() in {".otf", ".ttf", ".ttc"})
    assert faces, f"{FONTS_DIR} 里没有随包字体，字幕字面仍由系统决定"
    licenses = [p for p in FONTS_DIR.iterdir() if p.suffix.lower() == ".txt"]
    assert licenses, "字体缺随包授权文本"
    text = " ".join(p.read_text(encoding="utf-8", errors="replace") for p in licenses).upper()
    assert "OPEN FONT LICENSE" in text, "随包字体的授权文本不是 OFL，不能这样分发"


def test_caption_font_reports_the_family_from_the_font_file(tmp_path: Path) -> None:
    """族名以文件自报为准：声明与文件对不上时，随包字体的字面才是真相。"""
    _fake_font(tmp_path, "Probe Family Q")
    assert caption_font.caption_font(tmp_path).family == "Probe Family Q"


def test_caption_font_reads_the_shipped_face(tmp_path: Path) -> None:
    """改名过的副本读出来就是另一个族名——两条合起来才排除「常数抄对了」。"""
    real = caption_font.caption_font()
    assert real.family, "没读出族名"
    probe = _fake_font(tmp_path / "other", "Totally Different Family")
    font = caption_font.caption_font(probe.parent)
    assert font.family == "Totally Different Family"
    assert font.family != real.family


def test_caption_font_fails_loudly_when_the_bundle_is_missing(tmp_path: Path) -> None:
    """目录里没有字体就报错，不许回退系统字面：回退了拆行上限就失去标定对象。"""
    (tmp_path / "empty").mkdir()
    with pytest.raises(FileNotFoundError, match="fonts"):
        caption_font.caption_font(tmp_path / "empty")


# --------------------------------------------------------------- 三处共用这一份


def test_ass_style_asks_for_the_bundled_face() -> None:
    """预设里再写别的族名也不作数：样式行只认随包那份。"""
    preset: dict[str, Any] = {"font": {"name": "Microsoft YaHei", "size": 72}}
    assert _style_field(build_ass([], preset), 1) == caption_font.caption_font().family


def test_the_render_font_dir_points_at_the_bundle() -> None:
    """fontsdir 必须指向随包目录本身，不是临时目录、也不是系统字体目录。"""
    option = caption_font.fontsdir_option(caption_font.caption_font())
    assert option.startswith("fontsdir='") and option.endswith("'")
    inner = option[len("fontsdir='") : -1].replace("\\:", ":")
    assert Path(inner) == FONTS_DIR, f"fontsdir 指向 {inner}，而随包字体在 {FONTS_DIR}"


@pytest.mark.parametrize(
    "target",
    [
        *sorted((REPO_ROOT / "service/dramaclip/engines/subtitle").glob("*.py")),
        *sorted((REPO_ROOT / "resources/subtitle-presets").glob("*.json")),
        *(REPO_ROOT / "service/dramaclip/engines/exporter/encoder.py",),
    ],
)
def test_no_subtitle_source_names_a_system_font(target: Path) -> None:
    """门禁：字幕链路上任何一处再写系统族名，都会把渲染重新交回系统字体。"""
    text = target.read_text(encoding="utf-8")
    if target.suffix == ".json":
        font = json.loads(text).get("font", {})
        assert "name" not in font, f"{target.name} 的 font.name 已成死配置：族名由随包字体决定"
    hits = [family for family in _SYSTEM_FAMILIES if family in text]
    assert not hits, f"{target.name} 仍引用系统字体 {hits}"
