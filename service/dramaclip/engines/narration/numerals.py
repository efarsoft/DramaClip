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
    """0 ≤ num ≤ 9999 的段内读法（含段内零规则与「两千」惯例）。

    零的规则：高位读过之后，中间缺哪一位就补一个「零」，补过即复位——
    ``一百零二``（「一百二」口语里是一百二十）、``两千零二十六``。连续缺位只补一个。
    """
    parts: list[str] = []
    need_zero = False
    for value, name in ((1000, "千"), (100, "百"), (10, "十"), (1, "")):
        q, num = divmod(num, value)
        if q == 0:
            need_zero = need_zero or bool(parts)  # 中间缺位（更高位已读过）
            continue
        if need_zero:
            parts.append("零")
            need_zero = False
        if value == 10 and q == 1 and not parts:
            parts.append("十")  # 10~19 口语作「十X」不作「一十X」（十八，不是一十八）
        else:
            parts.append(("两" if q == 2 and value in (1000, 100) else _DIGITS[q]) + name)
    return "".join(parts) or "零"


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
    if match.group("date") or match.group("range"):
        # 日期（2026-10-22）与区间连写（3-4集/12-15年）读法不确定：整串放过。
        # 没有这两个分支，「3-4」会被负号分支读成「三负四」，比不转更糟。
        return match.group(0)
    if match.group("year"):
        return _year_cn(match.group("year")[: -len("年")].strip()) + "年"
    if match.group("pct"):
        return "百分之" + _decimal_cn(match.group("pct")[:-1])
    if match.group("ratio"):
        left, right = re.split(r"[:：]", match.group("ratio"))
        return _decimal_cn(left) + "比" + _decimal_cn(right)
    if match.group("dec"):
        return _decimal_cn(match.group("dec"))
    if match.group("neg"):
        # int_to_cn 对负数自带「负」前缀：这里再手写一个就产出「负负五」（实测）。
        return int_to_cn(int(match.group("neg")))
    # 已知边界（2026-11-04 审查 #20，评估后不动）：5-8 位无分隔数字串（如热线
    # 550300）按数量读成「五十五万零三百」——号码型误读。解说文案中出现频率
    # 极低；无分隔写法与真实大数无法在无上下文时区分，硬启发式（固定位数判
    # 号码）会把十万级金额误伤成不转换，比现状更糟。真出现时靠重掷反馈改写。
    return int_to_cn(int(match.group("int").replace(",", "")))


def _year_cn(digits: str) -> str:
    return "".join(_DIGITS[int(ch)] for ch in digits)


# 顺序即优先级：年份最窄先行，百分/比分/小数/负号各自整体吃掉，纯整数殿后。
# 年份允许数字与「年」之间夹空白（「2003 年」排版空格是常态，不认就读成「两千零三 年」）；
# 比分分支会吃掉 HH:MM 钟点（读成「八比三十」）——已知取舍：比分与钟点在文案里
# 无法可靠区分，宁可误读比分格式也不给钟点开第二套读法（两套必有一套错得更隐蔽）。
_TOKEN = re.compile(
    r"(?P<frac>\d+/\d+)"
    r"|(?P<date>\d{4}-\d{1,2}-\d{1,2})"
    r"|(?P<range>\d+-\d+)"
    r"|(?P<year>\d{4}\s*年)"
    r"|(?P<pct>\d+(?:\.\d+)?%)"
    r"|(?P<ratio>\d+(?:\.\d+)?[:：]\d+(?:\.\d+)?)"
    r"|(?P<dec>\d+\.\d+)"
    r"|(?P<neg>-\d+)"
    r"|(?P<int>\d{1,3}(?:,\d{3})+|\d+)"
)


def to_chinese_numerals(text: str) -> str:
    """文案里的阿拉伯数字 → 中文读法；认不出的组合整串放过，绝不半截转换。"""
    return _TOKEN.sub(_sub, text)


_CN_DIGITS = {char: value for value, char in enumerate(_DIGITS)} | {"〇": 0, "两": 2}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}
_CN_SECTIONS = {"万": 10_000, "亿": 100_000_000}


def cn_to_int(text: str) -> int | None:
    """中文数字 → 整数（``int_to_cn`` 的逆）；混进认不出的字符整串返回 None，不做半截解析。

    也认阿拉伯数字（全角归一、可混写）与年份那种逐位读法（二零零三）：连续的
    数字字符按位拼接，遇单位（十百千万亿）才结算——「一百零二」里的「零二」拼成 2，
    占位与逐位两种读法于是给出同一个数。
    """
    if not text:
        return None
    total = section = number = 0
    for char in text.translate(str.maketrans("０１２３４５６７８９", "0123456789")):
        if char.isdigit():
            number = number * 10 + int(char)
        elif char in _CN_DIGITS:
            number = number * 10 + _CN_DIGITS[char]
        elif char in _CN_UNITS:
            section += (number or 1) * _CN_UNITS[char]  # 「十五」「十万」：起头省了「一」
            number = 0
        elif char in _CN_SECTIONS:
            total = (total + section + number) * _CN_SECTIONS[char]
            section = number = 0
        else:
            return None
    return total + section + number
