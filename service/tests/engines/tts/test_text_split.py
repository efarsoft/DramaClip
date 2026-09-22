"""B7：split_long_text 纯函数——句末优先、CJK 上限÷2.5、碎块折回、空块计数。

上限常量的依据（写在 text_split.py 注释里）：latin 500 ≈ 云端 TTS 单请求舒适区，
CJK 200 = 500/2.5（中文信息密度约为拉丁字母的 2.5 倍，等时长口径）。
"""

from __future__ import annotations

from dramaclip.engines.tts.text_split import (
    CJK_MAX_CHARS,
    LATIN_MAX_CHARS,
    SplitResult,
    split_long_text,
)


def test_caps_relation_is_latin_div_2_5() -> None:
    assert LATIN_MAX_CHARS == 500
    assert CJK_MAX_CHARS * 5 == LATIN_MAX_CHARS * 2  # 200 = 500 / 2.5


def test_short_text_returns_single_chunk_untouched() -> None:
    text = "就一句话。"
    chunks, dropped = split_long_text(text)
    assert chunks == [text]
    assert dropped == 0


def test_splits_at_sentence_endings() -> None:
    text = "第一句。第二句！第三句？"
    chunks, dropped = split_long_text(text, max_chars=4)
    assert chunks == ["第一句。", "第二句！", "第三句？"]
    assert dropped == 0


def test_clause_split_when_sentence_too_long() -> None:
    text = "前半句，后半句。"
    chunks, _ = split_long_text(text, max_chars=4)
    assert chunks == ["前半句，", "后半句。"]


def test_whitespace_split_keeps_words_intact() -> None:
    text = ("alpha beta gamma " * 40).strip()  # 679 字符，无句读
    chunks, _ = split_long_text(text)
    assert len(chunks) >= 2
    assert all(len(c) <= LATIN_MAX_CHARS for c in chunks)
    for chunk in chunks:
        assert set(chunk.split()) <= {"alpha", "beta", "gamma"}, "空白层必须先于硬切"


def test_hard_cut_when_nothing_else_works() -> None:
    text = "字" * 1200
    chunks, _ = split_long_text(text)
    assert len(chunks) == 6  # 1200 / CJK 上限 200
    assert all(len(c) <= CJK_MAX_CHARS for c in chunks)
    assert "".join(chunks) == text, "硬切也不许丢字"


def test_cjk_text_uses_halved_cap() -> None:
    text = "这是很长的中文文案。" * 60  # 600 字符，CJK 占比 100%
    chunks, _ = split_long_text(text)
    assert all(len(c) <= CJK_MAX_CHARS for c in chunks)
    assert len(chunks) == 3
    # 关掉 cjk_aware：同一文本按 latin 500 上限 → 块数更少
    latin_chunks, _ = split_long_text(text, cjk_aware=False)
    assert all(len(c) <= LATIN_MAX_CHARS for c in latin_chunks)
    assert len(latin_chunks) < len(chunks)


def test_latin_text_uses_full_cap() -> None:
    text = "word. " * 120  # 720 字符，CJK 占比 0
    chunks, _ = split_long_text(text)
    assert len(chunks) == 2
    assert all(len(c) <= LATIN_MAX_CHARS for c in chunks)


def test_punct_only_fragment_folds_into_neighbour() -> None:
    text = "一二三。！！！四五六。"
    chunks, _ = split_long_text(text, max_chars=4)
    assert chunks == ["一二三。！！！", "四五六。"]
    assert all(any(not _is_punct(c) for c in chunk) for chunk in chunks)


def _is_punct(char: str) -> bool:
    return not char.isalnum() and not char.isspace()


def test_leading_punct_only_fragment_folds_forward() -> None:
    text = "？？？一二三。四五六。"
    chunks, _ = split_long_text(text, max_chars=4)
    # 首块纯标点没有「上一块」可折回，必须并入下一块而不是独立成块
    assert chunks[0].startswith("？？？")
    assert chunks[0] != "？？？"


def test_blank_text_yields_no_chunks_and_counts_the_drop() -> None:
    assert isinstance(split_long_text("   "), SplitResult)
    chunks, dropped = split_long_text("   ")
    assert chunks == []
    assert dropped == 1, "空 chunk 必须丢弃并计数（调用方诚实报告的凭据）"
    chunks2, dropped2 = split_long_text("")
    assert chunks2 == []
    assert dropped2 == 1


def test_explicit_max_chars_overrides_language_cap() -> None:
    text = "这一段解说文案。" * 30  # 240 字符 CJK
    chunks, _ = split_long_text(text, max_chars=120)
    assert len(chunks) == 2
    assert all(len(c) <= 120 for c in chunks)
    assert "".join(chunks) == text


def test_content_preservation_across_mixed_text() -> None:
    text = "他说：「走吧。」然后转身离开，再也没有回头。" * 20
    chunks, dropped = split_long_text(text)
    assert dropped == 0
    assert "".join(chunks) == text
