"""解说风格自动匹配：题材映射与手动优先。"""

from __future__ import annotations

import pytest

from dramaclip.engines.narration import styles


@pytest.mark.parametrize(
    ("genre", "expected"),
    [
        ("悬疑", "suspense"),
        ("复仇", "shuanggan"),
        ("逆袭", "shuanggan"),
        ("甜宠", "sweet"),
        ("家庭伦理", "emotional"),
        ("古装", "immersive"),
        ("都市", "general"),
        ("其他", "general"),
        ("", "general"),
        (None, "general"),
    ],
)
def test_auto_matches_genre(genre: str | None, expected: str) -> None:
    assert styles.resolve_style_id("auto", genre) == expected


def test_manual_choice_wins_over_auto() -> None:
    assert styles.resolve_style_id("comedy", "悬疑") == "comedy"
    assert styles.resolve_style_id("suspense", "甜宠") == "suspense"


def test_unknown_values_fall_back_to_general() -> None:
    assert styles.resolve_style_id("no-such-style", "悬疑") == "suspense"
    assert styles.resolve_style_id(None, None) == "general"


def test_auto_resolves_to_existing_builtin_styles() -> None:
    known = {style["style_id"] for style in styles.list_styles()}
    for genre in ("悬疑", "复仇", "甜宠", "古装", "都市", "其他"):
        assert styles.resolve_style_id("auto", genre) in known


def test_new_styles_registered_in_library() -> None:
    known = {style["style_id"]: style for style in styles.list_styles()}
    assert "sweet" in known and known["sweet"]["name"] == "甜宠撒糖"
    assert "inspiring" in known and known["inspiring"]["name"] == "热血燃向"
    # 新风格自动进入 LLM 选题菜单（菜单由 list_styles 动态生成）
    assert all(style.get("directives") for style in known.values())
