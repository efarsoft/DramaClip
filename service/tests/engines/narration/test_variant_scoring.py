"""B10 六维文案评分（引擎层）：解析防御、加权总分、确定性排序、prompt 行为锚点。

评分是**软信号**：只做排序与改进建议，绝不参与 grade/defects 硬门禁。
LLM 替身形状学 test_titles / test_angles（按队列应答 chat_json，不真调）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines import llm_prompts
from dramaclip.engines.narration import variant_scoring
from dramaclip.engines.semantic.llm_client import LlmUnavailable

_SETTINGS = {"llm.base_url": "https://x/v1", "llm.model": "m", "llm.api_key": "k"}

_FULL_DIMS = {
    "hook_power": 8,
    "rhythm": 7,
    "emotion_curve": 6,
    "conflict_clarity": 7,
    "cta_pull": 9,
    "visual_potential": 6,
}


def _row(plan_id: str, index: int = 1, mode: str = "full_narration") -> dict[str, Any]:
    return {
        "id": plan_id,
        "narration_mode": mode,
        "angle": f"角度{index}",
        "variant_index": index,
        "plan_data": {
            "mode": mode,
            "timeline": [{"episode_id": "ep1", "start": 0.0, "end": 3.0}],
            "narration_texts": [{"id": "n1", "text": f"方案{index}的解说文案，后面更狠"}],
        },
    }


class FakeClient:
    """按队列应答 chat_json；队列剩一条时重复应答（学 test_angles.FakeLlm）。"""

    def __init__(self, queue: list[Any]) -> None:
        self.queue = queue
        self.systems: list[str] = []
        self.users: list[str] = []
        self.calls = 0

    def chat_json(self, system: str, user: str) -> Any:
        self.calls += 1
        self.systems.append(system)
        self.users.append(user)
        item = self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]
        if isinstance(item, Exception):
            raise item
        return item


def _score(
    monkeypatch: pytest.MonkeyPatch,
    queue: list[Any],
    rows: list[dict[str, Any]],
    **settings: str,
) -> tuple[dict[str, dict[str, Any]], FakeClient]:
    client = FakeClient(queue)
    monkeypatch.setattr(variant_scoring, "LlmClient", lambda *a, **k: client)
    out = variant_scoring.score_variants(rows, {**_SETTINGS, **settings})
    return out, client


def _payload(entries: list[tuple[int, dict[str, Any], str]]) -> dict[str, Any]:
    return {
        "scores": [
            {"index": index, "dims": dims, "suggestion": suggestion}
            for index, dims, suggestion in entries
        ]
    }


# ── prompt 形状（钉行为锚点，防退化成抽象形容词） ─────────────────────────────


def test_prompt_carries_behavior_anchors_for_every_dim(monkeypatch) -> None:
    _, client = _score(monkeypatch, [_payload([(1, _FULL_DIMS, "建议")])], [_row("p1")])
    system = client.systems[0]
    assert "行为锚点" in system, "评分 prompt 必须声明按行为锚点打分"
    for dim in variant_scoring.DIMENSIONS:
        assert dim in system, f"prompt 少了维度 {dim}"
    # 每维都要有 9/7/5/3/1 五档具体描述：数锚点档位标记的出现次数
    for mark in ("9=", "7=", "5=", "3=", "1="):
        assert system.count(mark) >= len(variant_scoring.DIMENSIONS), (
            f"锚点档位 {mark} 不足六维各一条——prompt 退化成抽象形容词了"
        )
    assert "suggestion" in system and "index" in system, "输出契约没写进 prompt"


def test_prompt_registered_for_editing(monkeypatch) -> None:
    """与 titles/angles 同形：默认值在引擎模块，settings 可覆盖。"""
    assert "prompt.variant_scoring_system" in llm_prompts.SPEC_BY_KEY
    _, client = _score(
        monkeypatch,
        [_payload([(1, _FULL_DIMS, "建议")])],
        [_row("p1")],
        **{"prompt.variant_scoring_system": "只回 JSON。"},
    )
    assert client.systems[0] == "只回 JSON。"


# ── 一批多 variant：单次调用 ────────────────────────────────────────────────


def test_one_batch_is_scored_in_a_single_call(monkeypatch) -> None:
    rows = [_row(f"p{i}", i) for i in (1, 2, 3)]
    out, client = _score(
        monkeypatch,
        [_payload([(i, _FULL_DIMS, f"建议{i}") for i in (1, 2, 3)])],
        rows,
    )
    assert client.calls == 1, f"一批 3 条应只发一次请求，实得 {client.calls} 次"
    assert set(out) == {"p1", "p2", "p3"}
    assert out["p2"]["suggestion"] == "建议2"
    assert out["p1"]["dims"] == {k: float(v) for k, v in _FULL_DIMS.items()}
    user = client.users[0]
    for i in (1, 2, 3):
        assert f"[方案 {i}]" in user and f"方案{i}的解说文案" in user


def test_unconfigured_llm_raises(monkeypatch) -> None:
    client = FakeClient([_payload([(1, _FULL_DIMS, "建议")])])
    monkeypatch.setattr(variant_scoring, "LlmClient", lambda *a, **k: client)
    with pytest.raises(LlmUnavailable, match="引擎"):
        variant_scoring.score_variants([_row("p1")], {})
    assert client.calls == 0, "未配置就该在发请求之前停下"


def test_empty_rows_never_call_the_llm(monkeypatch) -> None:
    out, client = _score(monkeypatch, [_payload([])], [])
    assert out == {} and client.calls == 0


# ── 解析防御：钳 1-10、坏维度丢弃、整条丢弃 ─────────────────────────────────


def test_dims_are_clamped_and_bad_dims_dropped(monkeypatch) -> None:
    dims = {
        "hook_power": 12,  # 越上界 → 钳到 10
        "rhythm": -3,  # 越下界 → 钳到 1
        "emotion_curve": "很好",  # 非数值 → 丢弃
        "bogus_dim": 9,  # 未知维度 → 丢弃
        "conflict_clarity": 7,
        "cta_pull": 8,
        "visual_potential": 6,
    }
    out, _ = _score(monkeypatch, [_payload([(1, dims, "建议")])], [_row("p1")])
    parsed = out["p1"]["dims"]
    assert parsed["hook_power"] == 10.0
    assert parsed["rhythm"] == 1.0
    assert "emotion_curve" not in parsed and "bogus_dim" not in parsed
    assert set(parsed) == {"hook_power", "rhythm", "conflict_clarity", "cta_pull",
                           "visual_potential"}
    # 缺维不假装满分：total 只按在场维度归一
    expected = variant_scoring.weighted_total(parsed)
    assert out["p1"]["total"] == expected


def test_variant_without_any_valid_dim_is_dropped(monkeypatch) -> None:
    out, _ = _score(
        monkeypatch,
        [_payload([(1, {"bogus": 5}, "空话"), (2, _FULL_DIMS, "建议2")])],
        [_row("p1"), _row("p2", 2)],
    )
    assert set(out) == {"p2"}, "一个合法维度都没有的条目是幻觉，不该落进结果"


def test_out_of_range_index_is_ignored(monkeypatch) -> None:
    out, _ = _score(
        monkeypatch,
        [_payload([(1, _FULL_DIMS, "建议"), (99, _FULL_DIMS, "越界")])],
        [_row("p1")],
    )
    assert set(out) == {"p1"}


def test_bad_shape_raises_value_error(monkeypatch) -> None:
    with pytest.raises(ValueError, match="scores"):
        _score(monkeypatch, [{"nope": 1}], [_row("p1")])


# ── 失败重试与留痕 ──────────────────────────────────────────────────────────


def test_bad_response_is_retried_then_accepted(monkeypatch) -> None:
    out, client = _score(
        monkeypatch,
        [{"nope": 1}, _payload([(1, _FULL_DIMS, "建议")])],
        [_row("p1")],
    )
    assert client.calls == 2
    assert "p1" in out


def test_llm_failure_leaves_a_trace_and_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """两次尝试全败：抛给调用方降级（api 层 catch），但往返必须留痕可复盘。"""
    client = FakeClient([LlmUnavailable("网关 502")])
    monkeypatch.setattr(variant_scoring, "LlmClient", lambda *a, **k: client)
    with pytest.raises(ValueError, match="文案评分"):
        variant_scoring.score_variants([_row("p1")], _SETTINGS, trace_dir=tmp_path)
    assert client.calls == variant_scoring._ATTEMPTS
    traces = list(tmp_path.glob("llm_variant_scoring_*.json"))
    assert len(traces) == 1, f"评分失败未留痕：{sorted(p.name for p in traces)}"
    blob = json.loads(traces[0].read_text(encoding="utf-8"))
    assert blob["engine"] == "variant_scoring"
    assert len(blob["attempts"]) == 2
    assert all("网关 502" in str(item.get("error")) for item in blob["attempts"])


# ── 纯函数：加权总分与排序 ──────────────────────────────────────────────────


def test_weighted_total_is_a_weighted_sum_on_the_same_scale() -> None:
    assert variant_scoring.weighted_total({k: 10.0 for k in variant_scoring.DIMENSIONS}) == 10.0
    assert variant_scoring.weighted_total({k: 1.0 for k in variant_scoring.DIMENSIONS}) == 1.0
    # hook 与 cta_pull 是转化质量线的两端，权重必须并列最高
    weights = variant_scoring.WEIGHTS
    top = max(weights.values())
    assert weights["hook_power"] == top and weights["cta_pull"] == top
    assert sum(weights.values()) == pytest.approx(1.0)
    # 单维拉动可读：hook 满分其余 1 分，total 应显著高于 1
    mixed = {k: 1.0 for k in variant_scoring.DIMENSIONS}
    mixed["hook_power"] = 10.0
    assert variant_scoring.weighted_total(mixed) > 2.0


def test_weighted_total_renormalizes_when_dims_missing() -> None:
    partial = {"hook_power": 10.0, "cta_pull": 10.0}
    assert variant_scoring.weighted_total(partial) == 10.0
    with pytest.raises(ValueError):
        variant_scoring.weighted_total({})


def test_rank_orders_by_total_desc_and_breaks_ties_by_variant_index() -> None:
    rows = [
        {"id": "b", "score_total": 7.0, "variant_index": 2},
        {"id": "a", "score_total": 7.0, "variant_index": 1},
        {"id": "c", "score_total": 9.5, "variant_index": 3},
        {"id": "d", "score_total": 3.0, "variant_index": 1},
    ]
    ranked = variant_scoring.rank_variants(rows)
    assert [row["id"] for row in ranked] == ["c", "a", "b", "d"]


def test_rank_without_scores_keeps_the_current_order_verbatim() -> None:
    """硬验收：全无分数时返回值与入参逐项同序同对象——现状的逐字节降级。"""
    rows = [
        {"id": "x", "score_total": None, "variant_index": 2},
        {"id": "y", "score_total": None, "variant_index": 1},
        {"id": "z", "score_total": None, "variant_index": 3},
    ]
    ranked = variant_scoring.rank_variants(rows)
    assert ranked == rows
    assert [id(row) for row in ranked] == [id(row) for row in rows]


def test_rank_puts_unscored_rows_after_scored_ones_in_original_order() -> None:
    rows = [
        {"id": "u1", "score_total": None, "variant_index": 1},
        {"id": "s1", "score_total": 5.0, "variant_index": 2},
        {"id": "u2", "score_total": None, "variant_index": 3},
        {"id": "s2", "score_total": 8.0, "variant_index": 4},
    ]
    ranked = variant_scoring.rank_variants(rows)
    assert [row["id"] for row in ranked] == ["s2", "s1", "u1", "u2"]
