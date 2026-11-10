"""批量文案变异三件套（第一梯队①）：策略队列、避重块、3-gram 闸门与择优。纯逻辑。"""

from __future__ import annotations

import random

from dramaclip.engines.narration import diversity


def test_strategy_queue_no_adjacent_repeat_and_coverage() -> None:
    cards = diversity.strategy_queue(12, rng=random.Random(7))
    assert len(cards) == 12
    # 轮次衔接处不与上张同卡；8 张卡在第一轮全覆盖（洗牌取前 8）
    for prev, cur in zip(cards, cards[1:], strict=False):
        assert prev is not cur
    first_round = {c["name"] for c in cards[:8]}
    assert first_round == {c["name"] for c in diversity.STRATEGY_CARDS}


def test_past_copy_block_isolates_and_limits() -> None:
    block = diversity.past_copy_block(["旧稿甲" * 40, "旧稿乙" * 40, "旧稿丙" * 40, "更旧" * 40])
    assert block.startswith("<past_copy>") and "</past_copy>" in block
    assert "不可信引用文本" in block, "防注入声明必须在场"
    # 列表顺序=产出顺序（旧→新），最近 3 条=乙丙丁：最旧的甲被裁、最新的丁保留
    assert "旧稿乙" in block and "旧稿甲" not in block, "只取最近 3 条"
    assert diversity.past_copy_block([]) == ""


def test_dice_similarity_same_and_different() -> None:
    base = "他背着玄铁锅下了山，路上遇见了黑风寨的人，双方一言不合就动起手来。" * 3
    assert diversity.dice_similarity(base, base) == 1.0
    # 首句相同、后文完全重排 → 仍高相似（正文档）
    variant = base[:20] + "黑客帝国不是电影是纪录片而他根本没有下过任何一座山只是梦" * 3
    assert diversity.dice_similarity(base, variant) > 0.3
    # 完全不同文本 → 低
    other = "她把婚书扔进火里头也不回地走了出府的路上下起了今年第一场雪" * 3
    assert diversity.dice_similarity(base, other) < 0.3
    # 短文本（<80 字归一化后）不可靠：一律 0 不误杀
    assert diversity.dice_similarity("短文本", "短文本短文本短文本") == 0.0


def test_too_similar_body_and_head_gates() -> None:
    old = ("反派把账本拍在桌上，说他早就知道这一切都是局中局。主角攥紧了拳头。" * 4)[:200]
    near_copy = old[:190] + "完全不同的结尾文字若干若干若干若干若干若干若干若干若干若干若干。"
    assert diversity.too_similar(near_copy, [old]) is True
    fresh = "婚礼进行到一半新娘掀开盖头全场宾客发现她换了一张完全陌生的脸。" * 4
    assert diversity.too_similar(fresh, [old]) is False


def test_least_similar_picks_lower_worst_case() -> None:
    old = "他背着玄铁锅下了山，路上遇见了黑风寨的人，双方一言不合就动起手来。" * 3
    near = old[:150] + "稍有改动的结尾" * 10
    far = "她把婚书扔进火里头也不回地走了出府的路上下起了今年第一场雪。" * 3
    assert diversity.least_similar(near, far, [old]) is far
    assert diversity.least_similar(far, near, [old]) is far
    # 无基准：取首稿（省一次重合成）
    assert diversity.least_similar(near, far, []) is near
