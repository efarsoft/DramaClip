"""LLM 流式读取（第一梯队②）：SSE 聚合、非 SSE 回退标记、错误帧上抛。纯逻辑。"""

from __future__ import annotations

import io

import pytest

from dramaclip.engines.semantic.llm_client import (
    LlmClient,
    LlmUnavailable,
    _StreamUnavailable,
)


def _client() -> LlmClient:
    return object.__new__(LlmClient)  # 只测 _read_sse，跳过构造依赖


def test_sse_delta_frames_aggregate_in_order() -> None:
    sse = (
        b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
        b'ignore: not a data line\n\n'
        b'data: {"choices":[{"delta":{"content":" world"}}]}\n\n'
        b'data: {"choices":[{"delta":{}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    assert _client()._read_sse(io.BytesIO(sse)) == "hello world"


def test_plain_json_response_raises_fallback_marker() -> None:
    """网关忽略 stream 参数返回普通 JSON：不带 data: 前缀 → 回退非流式。"""
    plain = b'{"choices":[{"message":{"content":"x"}}]}'
    with pytest.raises(_StreamUnavailable):
        _client()._read_sse(io.BytesIO(plain))


def test_stream_with_no_content_frames_falls_back() -> None:
    """有 SSE 帧但全程无 content（空回答）：同样回退非流式路径裁决。"""
    sse = b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\ndata: [DONE]\n\n'
    with pytest.raises(_StreamUnavailable):
        _client()._read_sse(io.BytesIO(sse))


def test_error_frame_raises_llm_unavailable() -> None:
    sse = (
        b'data: {"error":{"message":"content inspection failed"}}\n\n'
    )
    with pytest.raises(LlmUnavailable, match="流式响应报错"):
        _client()._read_sse(io.BytesIO(sse))


def test_bad_json_line_skipped_not_fatal() -> None:
    sse = (
        b"data: not-json\n\n"
        b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    assert _client()._read_sse(io.BytesIO(sse)) == "ok"
