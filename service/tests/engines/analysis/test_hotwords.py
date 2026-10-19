"""merge_extra：人工热词并入挖掘表——业主点名是最强信号，永远排最前。"""

from __future__ import annotations

from dramaclip.engines.analysis.hotwords import merge_extra


def test_extra_leads_and_dedupes_mined() -> None:
    merged = merge_extra("锦衣卫 东厂 崇桢", "骆养性,王之心")
    assert merged == "骆养性 王之心 锦衣卫 东厂 崇桢"


def test_overlap_keeps_extra_position_not_mined_position() -> None:
    """同名词已在挖掘表：位置跟随 extra（人工点名优先），不重复出现。"""
    assert merge_extra("东厂 崇桢", "东厂 骆养性") == "东厂 骆养性 崇桢"


def test_all_separator_styles_accepted() -> None:
    """顿号/全角逗号/半角逗号/空格四种分隔都收。"""
    assert merge_extra("", "骆养性、王之心，崇祯,锦衣卫") == "骆养性 王之心 崇祯 锦衣卫"


def test_empty_extra_returns_mined_verbatim() -> None:
    """没配人工热词（或全是空白）：挖掘表原样透传，一个字都不动。"""
    assert merge_extra("锦衣卫 东厂", "") == "锦衣卫 东厂"
    assert merge_extra("锦衣卫 东厂", "，， 、 ") == "锦衣卫 东厂"
    assert merge_extra("", "") == ""
