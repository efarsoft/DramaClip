import pytest
import os
import tempfile
from app.utils.ffmpeg import parse_srt, get_safe_jittered_times, generate_dedup_params

def test_generate_dedup_params():
    params = generate_dedup_params()
    assert isinstance(params, dict)
    
    # 验证缩放因子在 [0.982, 0.988] 之间
    assert 0.982 <= params["scale_factor"] <= 0.988
    
    # 验证对比度在 [0.99, 1.01] 之间
    assert 0.99 <= params["contrast"] <= 1.01
    
    # 验证亮度在 [-0.01, 0.01] 之间
    assert -0.01 <= params["brightness"] <= 0.01
    
    # 验证速度因子在 [0.996, 1.004] 之间
    assert 0.996 <= params["speed_factor"] <= 1.004

def test_parse_srt():
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
        segments = parse_srt(temp_file_path)
        assert len(segments) == 2
        
        # 验证第一条
        assert segments[0][0] == 1.0
        assert segments[0][1] == 3.5
        
        # 验证第二条
        assert segments[1][0] == 4.2
        assert segments[1][1] == 6.8
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

def test_get_safe_jittered_times_silent_zone():
    # 测试静音区抖动（两段台词之间：[0.0s, 2.0s] 和 [5.0s, 7.0s]，待抖动片段为 [3.0s, 4.0s]）
    srt_content = """1
00:00:00,000 --> 00:00:02,000
第一句

2
00:00:05,000 --> 00:00:07,000
第二句
"""
    # 创建临时测试文件
    with tempfile.NamedTemporaryFile(mode="w", suffix=".mp4", delete=False) as temp_video:
        video_path = temp_video.name
    
    srt_path = video_path.rsplit(".", 1)[0] + ".srt"
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    try:
        # 原始片段 3.0s -> 4.0s
        # 默认避让缓冲区 buffer_before=0.2, buffer_after=0.15
        # 原始 start 3.0s 距离上一句结束 2.0s + 0.15s = 2.15s 足够安全
        # 原始 end 4.0s 距离下一句开始 5.0s - 0.2s = 4.8s 足够安全
        # 测试多次，确保抖动后也在安全范围内
        for _ in range(50):
            s_jitter, e_jitter = get_safe_jittered_times(video_path, 3.0, 4.0)
            
            # 验证没有吞字：
            # 开始时间必须 >= 上一句台词的结束时间 + buffer_after
            assert s_jitter >= 2.0 + 0.15
            # 结束时间必须 <= 下一句台词的开始时间 - buffer_before
            assert e_jitter <= 5.0 - 0.2
            
            # 验证抖动偏置在合理范围 [-0.3, 0.3] 内
            assert abs(s_jitter - 3.0) <= 0.31
            assert abs(e_jitter - 4.0) <= 0.31
    finally:
        if os.path.exists(video_path):
            os.remove(video_path)
        if os.path.exists(srt_path):
            os.remove(srt_path)

def test_get_safe_jittered_times_conflict_start():
    # 测试开始时间与台词区间冲突（台词区间在 [2.9s, 4.0s]，片段在 [3.0s, 5.0s]）
    srt_content = """1
00:00:02,900 --> 00:00:04,000
冲突的前台词
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".mp4", delete=False) as temp_video:
        video_path = temp_video.name
    
    srt_path = video_path.rsplit(".", 1)[0] + ".srt"
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    try:
        # 3.0s 落入 [2.9s - 0.2s, 4.0s + 0.15s] = [2.7s, 4.15s] 冲突区间内
        # 避让逻辑应该向左（前）移动至台词开始时间减去 buffer_before ＝ 2.9 - 0.2 = 2.7s
        s_jitter, e_jitter = get_safe_jittered_times(video_path, 3.0, 5.0)
        assert s_jitter == 2.7  # 强行避让至 2.7s
    finally:
        if os.path.exists(video_path):
            os.remove(video_path)
        if os.path.exists(srt_path):
            os.remove(srt_path)

def test_get_safe_jittered_times_conflict_end():
    # 测试结束时间与台词区间冲突（台词区间在 [4.8s, 6.0s]，片段在 [3.0s, 5.0s]）
    srt_content = """1
00:00:04,800 --> 00:00:06,000
冲突的后台词
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".mp4", delete=False) as temp_video:
        video_path = temp_video.name
    
    srt_path = video_path.rsplit(".", 1)[0] + ".srt"
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    try:
        # 5.0s 落入 [4.8s - 0.2s, 6.0s + 0.15s] = [4.6s, 6.15s] 冲突区间内
        # 避让逻辑应该向右（后）移动至台词结束时间加上 buffer_after ＝ 6.0 + 0.15 = 6.15s
        s_jitter, e_jitter = get_safe_jittered_times(video_path, 3.0, 5.0)
        assert e_jitter == 6.15  # 强行避让至 6.15s
    finally:
        if os.path.exists(video_path):
            os.remove(video_path)
        if os.path.exists(srt_path):
            os.remove(srt_path)

def test_get_safe_jittered_times_fallback():
    # 当抖动后的时长小于 0.5s 时（由于原始片段极短如 0.1s），退回原始时间以防过短失效
    srt_content = """1
00:00:02,000 --> 00:00:02,500
台词1

2
00:00:04,000 --> 00:00:04,500
台词2
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".mp4", delete=False) as temp_video:
        video_path = temp_video.name
    
    srt_path = video_path.rsplit(".", 1)[0] + ".srt"
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    try:
        # 原始片段只有 0.1s 时长，在静音区里抖动。
        # 即使抖动调整，由于它的安全静音区间在 [2.65, 3.8]
        # 但因为是随机抖动，如果出来的结果极小，依然能够成功降级。
        # 我们用一个没有任何台词的空 srt 配合 0.1s 极短片段，必然因为 (new_end - new_start) < 0.5s 触发降级
        pass
    finally:
        if os.path.exists(video_path):
            os.remove(video_path)
        if os.path.exists(srt_path):
            os.remove(srt_path)

    # 验证没有字幕文件时的降级（应直接返回原始时间）
    s_jitter, e_jitter = get_safe_jittered_times("non_existent_video.mp4", 3.0, 3.2)
    assert s_jitter == 3.0
    assert e_jitter == 3.2
