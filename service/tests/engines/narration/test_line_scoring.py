"""engines.narration.line_scoring：单句对白质量打分。"""

from __future__ import annotations

from dramaclip.engines.narration.line_scoring import score_line

# ---- 修辞结构分（2026-10-08 业主以《剑来》纠偏：文戏金句此前只得底分） ----


def test_jianlai_parallel_epic_scores_top() -> None:
    """「唯有一剑，可搬山，倒海，降妖…」零情绪词的千古名句必须高分。

    排比（≥4 个长度相近的并列成分 +24）+ 意象（剑/山/海/星 +12）。"""
    text = "我陈平安，唯有一剑，可搬山，倒海，降妖，镇魔，敕神，摘星，断江，摧城，开天。"
    assert score_line(text, 6.0) >= 70


def test_couplet_and_anadiplosis_recognized() -> None:
    """对仗（两半长度相近 +12）与顶真接龙（春风/春风 +14）各按修辞计分。"""
    couplet = score_line("但愿世间人无病，宁可架上药成灰。", 4.0)
    anadiplosis = score_line("遇事不决，可问春风；春风不语，既随本心。", 4.0)
    assert couplet >= 48
    assert anadiplosis > couplet, "顶真接龙应比对仗多一档"


def test_awakening_assertion_recognized() -> None:
    """世间清醒式断言（「世上」「理所应当」）给分，但不给排比级。"""
    assert score_line("世上除了爹娘，再没有人是理所应当对你好的", 3.5) >= 48


def test_conflict_lines_still_score_high() -> None:
    """冲突型狠话（爽剧主打）原有的高位不动。"""
    assert score_line("滚，废物！给我等着", 2.5) >= 68


def test_plain_line_stays_low() -> None:
    """废话台词不得高于任何修辞/冲突金句。"""
    plain = score_line("今天天气不错。", 2.0)
    assert plain < 40


def test_score_line_rewards_conflict_and_emotion() -> None:
    calm = score_line("今天天气不错", 3.0)
    angry = score_line("你给我滚！你这个废物！我要报仇！", 4.0)
    assert angry > calm + 30


def test_score_line_penalizes_odd_length() -> None:
    normal = score_line("正常的一句话", 3.0, independent=True)
    tiny = score_line("短", 0.8, independent=True)
    assert normal > tiny
