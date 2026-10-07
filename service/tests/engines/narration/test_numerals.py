"""文案数字中文化：确定性兜底的四个洞（外部会话审计钉出来的）都要钉死。"""

import random

from dramaclip.engines.narration.numerals import int_to_cn, to_chinese_numerals

# ① 任意整数不许抛（此前十万级 IndexError 击穿出片链重试环）


def test_large_values_do_not_raise() -> None:
    assert int_to_cn(100000) == "十万"
    assert int_to_cn(1000000) == "一百万"
    assert int_to_cn(1234567) == "一百二十三万四千五百六十七"
    assert int_to_cn(99999999) == "九千九百九十九万九千九百九十九"


def test_property_never_raises_under_1e8() -> None:
    rng = random.Random(42)
    for _ in range(2000):
        num = rng.randrange(100_000_000)
        out = int_to_cn(num)
        assert out


def test_out_of_range_passes_through() -> None:
    """亿级超出转换域：数字照转（一亿），「亿」字原文保留——读法正确即可。"""
    assert to_chinese_numerals("情报价值1亿两") == "情报价值一亿两"


# ③ 只认独立数字词，绝不产出半截货


def test_percent_ratio_decimal_negative() -> None:
    assert to_chinese_numerals("涨了50%") == "涨了百分之五十"
    assert to_chinese_numerals("比分2:1") == "比分二比一"
    assert to_chinese_numerals("冷却3.5秒") == "冷却三点五秒"
    assert to_chinese_numerals("零下18度") == "零下十八度", "下18 无负号：数值读法"
    assert to_chinese_numerals("翻了1/2倍") == "翻了1/2倍", "认不出的整串放过"


# ④ 零规则按口语


def test_zero_reading() -> None:
    assert to_chinese_numerals("1001") == "一千零一"
    assert to_chinese_numerals("10001") == "一万零一"
    assert to_chinese_numerals("10500") == "一万零五百"


# 年份逐位、千分位剥除、真机原文


def test_year_and_thousands() -> None:
    assert to_chinese_numerals("2003年的老楼") == "二零零三年的老楼"
    assert to_chinese_numerals("他背着2,000斤的玄铁锅") == "他背着两千斤的玄铁锅"
    assert to_chinese_numerals("8年前") == "八年前"


# Script 出口收口：hook/cta/segments 全覆盖


def test_script_fields_all_converted_at_exit() -> None:
    from dramaclip.engines.narration.scriptwriter import Script

    script = Script.model_validate(
        {
            "hook": "他背着2,000斤的玄铁锅，8年前封印修为",
            "segments": [
                {"episode": 1, "start": 0.0, "end": 3.0, "text": "涨了50%"},
                {"episode": 1, "start": 3.0, "end": 6.0, "text": "他背着玄铁锅"},
            ],
            "cta": "涨了50%以后点左下角",
        }
    )
    assert "2,000" not in script.hook and "2000" not in script.hook
    assert script.segments[0].text == "涨了百分之五十"
    assert script.segments[1].text == "他背着玄铁锅"
    assert script.cta.startswith("涨了百分之五十以后点左下角")
