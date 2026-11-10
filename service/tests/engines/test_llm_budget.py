"""任务级 LLM 等待预算（第一梯队⑤）：只计云端等待、渲染段冻结、嵌套取紧、耗尽抛错。"""

from __future__ import annotations

import time

import pytest

from dramaclip.engines.semantic import llm_budget
from dramaclip.engines.semantic.llm_budget import LlmBudgetExceeded


def test_no_budget_context_is_unlimited() -> None:
    assert llm_budget.remaining() is None
    assert llm_budget.check_and_timeout(240.0) == 240.0
    with llm_budget.paused():
        # 无预算下的 paused 是空操作，不是错误
        assert llm_budget.remaining() is None


def test_check_clamps_timeout_to_remaining() -> None:
    with llm_budget.budget(60.0):
        # 剩余 < 请求值：read 超时被压到剩余预算
        assert llm_budget.check_and_timeout(240.0) <= 60.0
        assert llm_budget.check_and_timeout(10.0) == 10.0


def test_exhausted_budget_raises() -> None:
    with llm_budget.budget(0.0), pytest.raises(LlmBudgetExceeded):
        llm_budget.check_and_timeout(240.0)


def test_paused_freezes_then_restores() -> None:
    with llm_budget.budget(5.0):
        with llm_budget.paused():
            # 冻结段：预算上下文摘下（本段是 CPU 工作，没有 LLM 调用）
            assert llm_budget.remaining() is None
            time.sleep(0.05)
        # 恢复后剩余 ≈ 原值（冻结期间不计时）
        assert llm_budget.remaining() is not None
        assert llm_budget.remaining() > 4.9


def test_nested_budget_takes_tighter() -> None:
    with llm_budget.budget(100.0):
        with llm_budget.budget(10.0):
            assert llm_budget.remaining() is not None
            assert llm_budget.remaining() <= 10.0
        # 内层退出恢复外层
        assert llm_budget.remaining() is not None
        assert llm_budget.remaining() > 10.0


def test_open_close_pair_restores_on_exception() -> None:
    saved = llm_budget.open_budget(30.0)
    try:
        llm_budget.open_budget(1.0)
        raise RuntimeError("boom")
    except RuntimeError:
        pass
    finally:
        llm_budget.close_budget(saved)
    assert llm_budget.remaining() is None  # 回到无预算态
