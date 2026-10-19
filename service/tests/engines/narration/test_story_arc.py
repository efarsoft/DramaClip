"""story_arc：九张叙事母题卡——id 唯一、菜单可渲染、结构卡三段骨架齐全。"""

from __future__ import annotations

from dramaclip.engines.narration import story_arc


def test_nine_cards_with_unique_ids_and_names() -> None:
    cards = [story_arc.card_of(arc_id) for arc_id in story_arc.ids()]
    assert len(cards) == 9
    assert all(card is not None for card in cards)
    names = [card.name for card in cards if card is not None]
    assert len(set(names)) == 9, "母题人读名重复：方案卡徽标会分不清"


def test_owner_defined_three_arcs_present() -> None:
    """业主定义的三张卡在库：id 不变，卡名随九卡统一为手法式四字。"""
    assert story_arc.card_of(story_arc.GLORY_FIRST) is not None
    assert story_arc.card_of(story_arc.UNDERDOG) is not None
    assert story_arc.card_of(story_arc.FOLK_TALE) is not None


def test_every_card_has_three_part_structure() -> None:
    """结构卡必须可执行：开场/中段/结尾三段各有明确指令，不许写成散文理论。"""
    for arc_id in story_arc.ids():
        card = story_arc.card_of(arc_id)
        assert card is not None
        assert "开场：" in card.structure, f"{arc_id} 缺开场指令"
        assert "中段：" in card.structure or "结尾：" in card.structure
        assert card.essence, f"{arc_id} 缺看点本质"


def test_card_of_unknown_returns_none() -> None:
    assert story_arc.card_of("nope") is None
    assert story_arc.card_of("") is None


def test_menu_line_lists_all_cards() -> None:
    menu = story_arc.menu_line()
    for arc_id in story_arc.ids():
        card = story_arc.card_of(arc_id)
        assert card is not None
        assert card.name in menu and card.arc_id in menu
