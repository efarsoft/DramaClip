"""文案数字中文化：阿拉伯数字是报表写法，配音念出来必怪（真机 2,000 斤事故）。

LLM 对「数字写中文」指令的遵从率不稳——格式问题不用提示词治，落库前用
确定性转换兜底：千分位剥除 + 数值读法 + 年份逐位读法。
"""

from dramaclip.engines.narration.numerals import to_chinese_numerals


def test_thousands_separator_and_years() -> None:
    """真机事故原文：2,000 斤 + 8 年前。"""
    assert to_chinese_numerals("他背着2,000斤的玄铁锅") == "他背着两千斤的玄铁锅"
    assert to_chinese_numerals("8年前把她拽回来") == "八年前把她拽回来"


def test_year_reads_digit_by_digit() -> None:
    assert to_chinese_numerals("2003年的老楼") == "二零零三年的老楼"
    assert to_chinese_numerals("等了2003年") == "等了二零零三年"


def test_plain_values() -> None:
    assert to_chinese_numerals("账上只剩47块") == "账上只剩四十七块"
    assert to_chinese_numerals("带了20000兵") == "带了两万兵"
    assert to_chinese_numerals("10个打1个") == "十个打一个"
    assert to_chinese_numerals("她今年18岁") == "她今年十八岁"
