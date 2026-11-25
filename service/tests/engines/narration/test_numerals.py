"""文案数字中文化：确定性兜底的四个洞（外部会话审计钉出来的）都要钉死。"""

import random

import pytest

from dramaclip.engines.narration.numerals import cn_to_int, int_to_cn, to_chinese_numerals

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


def test_negative_single_prefix_not_double() -> None:
    """负号分支与 int_to_cn 各加一次「负」=「负负五」（实测）：前缀只许出现一次。"""
    assert to_chinese_numerals("气温-5度") == "气温负五度"
    assert to_chinese_numerals("-12城") == "负十二城"


def test_date_and_range_pass_through_untouched() -> None:
    """日期与区间连写读法不确定：整串放过，绝不被负号分支读成「三负四」。"""
    assert to_chinese_numerals("第3-4集") == "第3-4集"
    assert to_chinese_numerals("12-15年") == "12-15年"
    assert to_chinese_numerals("2026-10-22") == "2026-10-22"


def test_year_with_space_still_reads_digit_by_digit() -> None:
    """「2003 年」排版空格是常态：年份分支必须容忍，读出「二零零三年」。"""
    assert to_chinese_numerals("2003 年 spring") == "二零零三年 spring"


# 内零：中间缺哪一位补一个「零」，补过即复位
# （2026-11-24 对拍实锤：0..99999 里 15.39% 的数读错——缺十位不补零、补零不复位两类）


@pytest.mark.parametrize(
    ("num", "expected"),
    [
        # 缺十位：此前读成「一百二」（口语里那是一百二十）
        (101, "一百零一"),
        (102, "一百零二"),
        (109, "一百零九"),
        (202, "两百零二"),
        # 补零不复位：此前读成「一千零一十零一」「两千零二十零六」
        (1005, "一千零五"),
        (1010, "一千零一十"),
        (1011, "一千零一十一"),
        (2026, "两千零二十六"),
        (10050, "一万零五十"),
        (10101, "一万零一百零一"),
        (6076577, "六百零七万六千五百七十七"),
        # 别矫枉过正：没有内零的读法原样不动
        (0, "零"),
        (12, "十二"),
        (20, "二十"),
        (110, "一百一十"),
        (200000, "二十万"),
        (1000000, "一百万"),
    ],
)
def test_inner_zero_reading(num: int, expected: str) -> None:
    assert int_to_cn(num) == expected


def test_episode_numbers_over_a_hundred_read_with_the_zero() -> None:
    """短剧上百集是常态：「第102集」不许念成「第一百二集」（听着是一百二十集）。"""
    assert to_chinese_numerals("讲到第102集") == "讲到第一百零二集"
    assert to_chinese_numerals("第105集") == "第一百零五集"


def test_int_to_cn_round_trips_through_cn_to_int() -> None:
    """全量 0..99999：转出去再解析回来必须等于原数——内零的两类错误都逃不过这条。"""
    bad = [n for n in range(100_000) if cn_to_int(int_to_cn(n)) != n]
    assert bad == [], f"读法与解析对不上的数（前 8 个）：{bad[:8]}"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("三十五", 35),
        ("十", 10),
        ("十五", 15),
        ("一百零二", 102),
        ("两千零二十六", 2026),
        ("一千零一十一", 1011),
        ("十二万", 120_000),
        ("两百", 200),
        ("二零零三", 2003),  # 年份逐位读法
        ("１２", 12),  # 全角数字
        ("35", 35),
        ("一百零二万", 1_020_000),
        ("一百零三集", None),  # 混了别的字：整串认不出就是 None，不做半截解析
        ("第", None),
        ("", None),
    ],
)
def test_cn_to_int(text: str, expected: int | None) -> None:
    assert cn_to_int(text) == expected
