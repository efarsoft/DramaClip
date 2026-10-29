"""结尾词级出点检查（T1 质批）：成片最后一刀切在对白的什么位置。"""

from dramaclip.engines.exporter.selfcheck import check_ending

LINES = [
    (30.0, 31.5, "首富之子汪大少要结婚了。"),
    (31.6, 34.5, "我作为未婚妻，不该过来看看吗？"),
    (35.0, 36.5, "你猜他为了谁悔婚"),
    (36.6, 38.5, "就是为了我们家的生意"),
    (38.8, 40.9, "所以，跟你这位江城第一总裁的婚约，也自动取消了"),
]


def test_cut_inside_a_line_is_mid_line() -> None:
    check = check_ending(33.0, LINES)  # 切在「不该过来看看吗」句中
    assert check["pass"] is False and check["reason"] == "mid_line"


def test_question_without_its_answer_is_mid_sentence() -> None:
    # 切在问句（非句末标点）之后 0.6s 内有下句=答没录进来
    check = check_ending(36.6, LINES)
    assert check["pass"] is False and check["reason"] == "mid_sentence"


def test_cut_after_sentence_end_passes() -> None:
    check = check_ending(34.5, LINES)  # 句号句尾完整出点
    assert check["pass"] is True


def test_no_data_is_none() -> None:
    assert check_ending(None, None)["pass"] is None
    assert check_ending(34.5, None)["pass"] is None
