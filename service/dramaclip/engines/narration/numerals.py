"""文案数字中文化：阿拉伯数字是报表写法，配音念出来必怪（真机 2,000 斤事故）。

LLM 对「数字写中文」的指令遵从率不稳——格式类问题不用提示词治，成稿清洗时
用确定性转换兜底。四条硬规矩（外部会话审计钉出来的四个洞）：
- 任意整数不许抛：十万级此前 IndexError 会击穿出片链的重试环（生产阻断级）；
- 只认独立数字词：百分号/比分/小数/负号各按读法**整体**转换，绝不产出半截货
  （五十%、二:一 这种比不转更糟）；
- 年份（四位数字+「年」）逐位读（2003 年→二零零三年），其余按数值读；
- 零规则按口语：一千零一、一万零一（连续零只补一个）。

认不出的组合（1/2、4K 等）整串原样放过——宁可放过，不做半截转换。
"""

from __future__ import annotations

import re

_DIGITS = "零一二三四五六七八九"


def _thousands(num: int) -> str:
    """0 ≤ num ≤ 9999 的段内读法（含段内零规则与「两千」惯例）。"""
    parts: list[str] = []
    need_zero = False
    for value, name in ((1000, "千"), (100, "百")):
        q, num = divmod(num, value)
        if q:
            if need_zero:
                parts.append("零")
            parts.append(("两" if q == 2 and value == 1000 else _DIGITS[q]) + name)
        elif parts and num > 0:
            need_zero = True
    q, num = divmod(num, 10)
    if q:
        if need_zero:
            parts.append("零")
        parts.append(_DIGITS[q] + "十")
    if num or not parts:
        if need_zero:
            parts.append("零")
        parts.append(_DIGITS[num])
    text = "".join(parts)
    # 10~19 口语作「十X」不作「一十X」（十八，不是一十八）
    if text.startswith("一十"):
        text = text[1:]
    return text


def int_to_cn(num: int) -> str:
    """整数 → 中文读法；0 ≤ num < 1e8 全区间无异常，超界原样返回阿拉伯数字。"""
    if num < 0:
        return "负" + int_to_cn(-num)
    if num >= 100_000_000:
        return str(num)
    w, rest = divmod(num, 10_000)
    if w == 0:
        return _thousands(num)
    head = ("两" if w == 2 else _thousands(w)) + "万"
    if rest == 0:
        return head
    if rest < 1000:
        return head + "零" + _thousands(rest)
    return head + _thousands(rest)


def _decimal_cn(text: str) -> str:
    """整段（可含小数点）→ 中文；小数部分逐位读（三点五）。"""
    if "." in text:
        whole, frac = text.split(".", 1)
        return int_to_cn(int(whole)) + "点" + "".join(_DIGITS[int(ch)] for ch in frac)
    return int_to_cn(int(text))


def _sub(match: re.Match[str]) -> str:
    if match.group("frac"):
        return match.group("frac")  # 1/2 这类分数读法不确定：整串放过，不做半截转换
    if match.group("year"):
        return _year_cn(match.group("year")[: -len("年")]) + "年"
    if match.group("pct"):
        return "百分之" + _decimal_cn(match.group("pct")[:-1])
    if match.group("ratio"):
        left, right = re.split(r"[:：]", match.group("ratio"))
        return _decimal_cn(left) + "比" + _decimal_cn(right)
    if match.group("dec"):
        return _decimal_cn(match.group("dec"))
    if match.group("neg"):
        return "负" + int_to_cn(int(match.group("neg")))
    return int_to_cn(int(match.group("int").replace(",", "")))


def _year_cn(digits: str) -> str:
    return "".join(_DIGITS[int(ch)] for ch in digits)


# 顺序即优先级：年份最窄先行，百分/比分/小数/负号各自整体吃掉，纯整数殿后
_TOKEN = re.compile(
    r"(?P<frac>\d+/\d+)"
    r"|(?P<year>\d{4}年)"
    r"|(?P<pct>\d+(?:\.\d+)?%)"
    r"|(?P<ratio>\d+(?:\.\d+)?[:：]\d+(?:\.\d+)?)"
    r"|(?P<dec>\d+\.\d+)"
    r"|(?P<neg>-\d+)"
    r"|(?P<int>\d{1,3}(?:,\d{3})+|\d+)"
)


def to_chinese_numerals(text: str) -> str:
    """文案里的阿拉伯数字 → 中文读法；认不出的组合整串放过，绝不半截转换。"""
    return _TOKEN.sub(_sub, text)
