"""文案数字中文化：阿拉伯数字是报表写法，配音念出来必怪（真机 2,000 斤事故）。

LLM 对「数字写中文」的指令遵从率不稳——格式类问题不用提示词治，
落库前用确定性转换兜底：千分位剥除 + 数值读法（2000→两千）+ 年份读法
（2003 年→二零零三年，逐位）。
"""

from __future__ import annotations

import re

_DIGITS = "零一二三四五六七八九"
_UNITS = ["", "十", "百", "千"]


def _value_to_cn(num: int) -> str:
    """整数 → 中文数值读法（2000→两千，10500→一万零五百，47→四十七）。"""
    if num < 0 or num >= 100_000_000:
        return str(num)
    if num < 10:
        return _DIGITS[num]
    if num < 20:
        return "十" if num == 10 else "十" + _DIGITS[num % 10]
    parts: list[str] = []
    for group, unit in ((10_000, "万"), (1_000, "千"), (100, "百"), (10, "十")):
        if num >= group:
            q, num = divmod(num, group)
            if group >= 1000:
                # 惯例：段首的「二」读「两」（两千/两万），中间位仍读二
                prefix = "两" if q == 2 and not parts else _DIGITS[q]
            else:
                prefix = _value_to_cn(q)
            parts.append(prefix + unit)
        if parts and 0 < num < group // 10 and num < 10:
            parts.append("零")
    if num > 0 or not parts:
        parts.append(_DIGITS[num] if num < 10 else _value_to_cn(num))
    text = "".join(parts)
    # 「一十X」口语作「十X」；万级之后保留「一十万」之外的规整形式
    if text.startswith("一十"):
        text = text[1:]
    return text


def _year_to_cn(digits: str) -> str:
    """年份逐位读法：2003→二零零三（零不可省）。"""
    return "".join(_DIGITS[int(ch)] for ch in digits)


def _replace_number(match: re.Match[str]) -> str:
    digits = match.group("digits").replace(",", "")
    if match.group("year") and len(digits) == 4:
        return _year_to_cn(digits) + "年"
    return _value_to_cn(int(digits)) + (match.group("year") or "")


# 年份探针：四位数字后紧跟「年」；year 组只用于判定读法，替换时并入
_NUM_PATTERN = re.compile(r"(?P<digits>\d{1,3}(?:,\d{3})+|\d+)(?P<year>年)?")


def to_chinese_numerals(text: str) -> str:
    """文案里的阿拉伯数字 → 中文读法（千分位剥除；四位+「年」走年份逐位读）。"""
    return _NUM_PATTERN.sub(_replace_number, text)
