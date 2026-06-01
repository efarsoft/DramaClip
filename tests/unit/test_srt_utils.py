import os
import tempfile
import pytest
from app.utils.srt_utils import (
    seconds_to_srt_time,
    parse_srt_time,
    create_simple_srt,
    parse_srt_file,
    concat_srt_files,
    SrtEntry
)

def test_seconds_to_srt_time():
    assert seconds_to_srt_time(0.0) == "00:00:00,000"
    assert seconds_to_srt_time(1.5) == "00:00:01,500"
    assert seconds_to_srt_time(3661.05) == "01:01:01,050"

def test_parse_srt_time():
    assert parse_srt_time("00:00:00,000") == 0.0
    assert parse_srt_time("00:00:01,500") == 1.5
    assert parse_srt_time("01:01:01.050") == 3661.05
    assert parse_srt_time("invalid") == 0.0

def test_parse_srt_file():
    srt_content = """1
00:00:01,000 --> 00:00:03,500
你好，欢迎使用 DramaClip。

2
00:00:04,200 --> 00:00:06,800
这是一个智能剪辑系统。
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False, encoding="utf-8") as temp_file:
        temp_file.write(srt_content)
        temp_file_path = temp_file.name

    try:
        entries = parse_srt_file(temp_file_path)
        assert len(entries) == 2
        
        assert entries[0].index == 1
        assert entries[0].start_time == 1.0
        assert entries[0].end_time == 3.5
        assert entries[0].text == "你好，欢迎使用 DramaClip。"
        
        assert entries[1].index == 2
        assert entries[1].start_time == 4.2
        assert entries[1].end_time == 6.8
        assert entries[1].text == "这是一个智能剪辑系统。"
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

def test_concat_srt_files():
    srt_content_1 = """1
00:00:01,000 --> 00:00:03,000
第一句话。
"""
    srt_content_2 = """1
00:00:02,000 --> 00:00:05,000
第二句话。
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False, encoding="utf-8") as tf1:
        tf1.write(srt_content_1)
        tf_path_1 = tf1.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False, encoding="utf-8") as tf2:
        tf2.write(srt_content_2)
        tf_path_2 = tf2.name

    out_file = tempfile.mktemp(suffix=".srt")

    try:
        # 合并两个 SRT 文件，初始时间偏移为 0.0
        success = concat_srt_files([tf_path_1, tf_path_2], out_file, time_offset=0.0)
        assert success is True
        
        # 解析合并后的文件
        merged = parse_srt_file(out_file)
        assert len(merged) == 2
        
        # 第一条：偏移是 0.0
        # start: 0.0 + 1.0 = 1.0
        # end: 0.0 + 3.0 = 3.0
        assert merged[0].index == 1
        assert merged[0].start_time == 1.0
        assert merged[0].end_time == 3.0
        assert merged[0].text == "第一句话。"
        
        # 第一条结束后，偏移更新为 file_start + last.end_time = 0.0 + 3.0 = 3.0
        # 第二条：偏移是 3.0
        # start: 3.0 + 2.0 = 5.0
        # end: 3.0 + 5.0 = 8.0
        assert merged[1].index == 2
        assert merged[1].start_time == 5.0
        assert merged[1].end_time == 8.0
        assert merged[1].text == "第二句话。"
        
    finally:
        for p in [tf_path_1, tf_path_2, out_file]:
            if os.path.exists(p):
                os.remove(p)
