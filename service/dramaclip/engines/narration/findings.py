"""审查报告数据结构：Finding 与 ReviewReport。

自 audit.py 拆出（拆分专项）：两个 dataclass 是 audit（script 审查）与
copy_audit（copy 审查）的共享契约——规则函数产出 Finding，总入口汇总成
ReviewReport。放在独立模块让两侧都单向依赖它，不互相 import。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Finding:
    rule_id: str
    layer: str          # structure | fund_base | fund_full | fund_slot | copy
    severity: str       # hard | soft
    passed: bool
    message: str
    location: str = ""              # 出问题的字段路径，如 segment[3].text
    prompt_quote: str = ""          # 该规则对应的 prompt 原文（溯源）
    needs_human: bool = False       # soft 规则默认需人工复核
    # 可执行修法（指出问题不算批评，批评必须带怎么改——重掷/重写循环吃这条；
    # 给不出具体修法的问题就别填，空串=只有定位没有修法）
    fix_hint: str = ""


@dataclass
class ReviewReport:
    target: str                     # "script" | "copy"
    findings: list[Finding] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def hard_fails(self) -> list[Finding]:
        return [f for f in self.findings if not f.passed and f.severity == "hard"]

    @property
    def soft_flags(self) -> list[Finding]:
        return [f for f in self.findings if not f.passed and f.severity == "soft"]

    @property
    def passed(self) -> bool:
        return not self.hard_fails

    def summary_line(self) -> str:
        return (
            f"[{self.target}] hard_fail={len(self.hard_fails)} "
            f"soft_flag={len(self.soft_flags)} "
            f"verdict={'REJECT' if self.hard_fails else 'PASS'}"
        )
