"""transport.connection：行分帧与地址解析（纯逻辑）。"""

from __future__ import annotations

import pytest

from dramaclip.transport.connection import LineAssembler, parse_address


def test_parse_address_valid() -> None:
    assert parse_address("127.0.0.1:51800") == ("127.0.0.1", 51800)


def test_parse_address_rejects_invalid() -> None:
    for bad in ("", "localhost", "127.0.0.1", "host:abc", ":1234"):
        with pytest.raises(ValueError, match="非法服务地址"):
            parse_address(bad)


def test_single_complete_line() -> None:
    assembler = LineAssembler()
    assert assembler.feed(b'{"a":1}\n') == ['{"a":1}']


def test_line_split_across_chunks() -> None:
    assembler = LineAssembler()
    assert assembler.feed(b'{"js') == []
    assert assembler.feed(b'onrpc":"2.0"}\n') == ['{"jsonrpc":"2.0"}']


def test_multiple_lines_in_one_chunk() -> None:
    assembler = LineAssembler()
    lines = assembler.feed(b'{"a":1}\n{"b":2}\n{"c":3}\n')
    assert lines == ['{"a":1}', '{"b":2}', '{"c":3}']


def test_empty_lines_skipped_and_partial_kept() -> None:
    assembler = LineAssembler()
    assert assembler.feed(b'{"a":1}\n\n{"b":2}\n{"part') == ['{"a":1}', '{"b":2}']
    assert assembler.feed(b'ial":true}\n') == ['{"partial":true}']


def test_utf8_multibyte_split_across_chunks() -> None:
    assembler = LineAssembler()
    payload = '{"msg":"中文"}\n'.encode()
    half = len(payload) // 2
    assert assembler.feed(payload[:half]) == []
    assert assembler.feed(payload[half:]) == ['{"msg":"中文"}']
