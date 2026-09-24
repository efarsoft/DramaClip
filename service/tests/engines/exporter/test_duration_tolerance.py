"""时长审计容差只有一个真相源：`encoder.AUDIT_DURATION_*`。

三处判据（`api/export._audit_duration` 渲染后 warn、`encoder._audit_film_duration`
段和 warn、`selfcheck.check_duration` 成品库红绿门禁）过去各写一份 0.08 / 3.0，
靠三段注释互相指认"同判据"。注释不改代码：改一处就出现「界面绿、日志 warn」。
本文件把「它们是同一个数」从注释升级成门禁。
"""

from __future__ import annotations

import re
from pathlib import Path

from dramaclip.api import export as export_api
from dramaclip.engines.exporter import encoder, selfcheck

_SITES = (Path(encoder.__file__), Path(export_api.__file__), Path(selfcheck.__file__))
# `某容差 = 数字`：字面量落地处（import 进来的引用不会命中，等号左边没有 TOLERANCE）
_INLINE_DEFINITION = re.compile(r"^(\w*TOLERANCE\w*)\s*=\s*[-\d]", re.MULTILINE)


def test_only_encoder_hands_out_the_tolerance_numbers() -> None:
    """三处判据里，只有 encoder 允许出现「容差 = 字面量」的定义行。"""
    offenders = [
        f"{site.name}:{body[: match.start()].count(chr(10)) + 1} {match.group(1)}"
        for site in _SITES
        for body in [site.read_text(encoding="utf-8")]
        for match in _INLINE_DEFINITION.finditer(body)
        if site != Path(encoder.__file__)
    ]
    assert offenders == [], f"时长容差出现第二处真相源：{offenders}"


def test_the_other_two_sites_read_encoders_constant() -> None:
    """另两处必须点名引用 encoder 的常量（不引用就是自己算了一套）。"""
    for site in (Path(export_api.__file__), Path(selfcheck.__file__)):
        body = site.read_text(encoding="utf-8")
        assert "AUDIT_DURATION_REL_TOLERANCE" in body, f"{site.name} 没引用共享相对容差"
        assert "AUDIT_DURATION_ABS_TOLERANCE_S" in body, f"{site.name} 没引用共享绝对容差"


def test_selfcheck_gate_boundary_is_the_shared_pair() -> None:
    """界面门禁的边界就是 max(8%, 3s)：64s/60s 放行、5s 漂移判失败。

    只钉这一个数就够：自检那条是**用户看得见的红绿**，它与日志侧分叉时的
    症状正是「成片库里绿着，日志却在 warn」。
    """
    assert selfcheck.check_duration(64.0, 60.0)["pass"] is True, "4s 漂移在 8% 内，应放行"
    assert selfcheck.check_duration(65.0, 60.0)["pass"] is False, "5s 漂移已出线，应判失败"
    # 10s 预算的 8% 只有 0.8s；漂移 1s 能放行，靠的是 3s 绝对下限那一档
    assert selfcheck.check_duration(11.0, 10.0)["pass"] is True, "短片由 3s 绝对下限兜住"
