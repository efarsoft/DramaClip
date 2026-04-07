"""
DramaClip - SRT 字幕工具函数

提供 SRT 时间戳转换、解析、合并等通用功能，
避免在 direct_cut 和 narration pipeline 中重复实现。
"""

import os
import re
from typing import List, Tuple, Optional
from loguru import logger


def seconds_to_srt_time(seconds: float) -> str:
    """
    将秒数转换为 SRT 时间字符串格式 (HH:MM:SS,mmm)
    
    Args:
        seconds: 秒数
        
    Returns:
        SRT 格式时间字符串, 如 "00:01:23,456"
    """
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt_time(srt_time_str: str) -> float:
    """
    将 SRT 时间字符串转换为秒数
    
    支持格式: HH:MM:SS,mmm 或 HH:MM:SS.mmm
    
    Args:
        srt_time_str: SRT 时间字符串
        
    Returns:
        浮点数秒数
    """
    try:
        srt_time_str = srt_time_str.replace(',', '.')
        parts = srt_time_str.split(':')
        h = int(parts[0])
        m = int(parts[1])
        s = float(parts[2])
        return h * 3600 + m * 60 + s
    except Exception as e:
        logger.debug(f"SRT时间解析失败 '{srt_time_str}': {e}")
        return 0.0


def create_simple_srt(text: str, start: float, duration: float, output_path: str):
    """创建简单的SRT字幕文件"""
    lines = text.strip().split('\n')[:5]  # 最多5行
    with open(output_path, 'w', encoding='utf-8') as f:
        for i, line in enumerate(lines):
            start_hms = seconds_to_srt_time(start + (duration * i / len(lines)))
            end_hms = seconds_to_srt_time(start + (duration * (i + 1) / len(lines)))
            f.write(f"{i+1}\n{start_hms} --> {end_hms}\n{line.strip()}\n\n")


class SrtEntry:
    """单条 SRT 条目"""
    __slots__ = ('index', 'start_time', 'end_time', 'text')
    
    def __init__(self, index: int, start_time: float, end_time: float, text: str):
        self.index = index
        self.start_time = start_time
        self.end_time = end_time
        self.text = text


def parse_srt_file(srt_path: str) -> List[SrtEntry]:
    """
    解析 SRT 文件为结构化条目列表
    
    Args:
        srt_path: SRT 文件路径
        
    Returns:
        SrtEntry 列表
    """
    entries = []
    try:
        with open(srt_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        blocks = re.split(r'\n\n+', content.strip())
        for block in blocks:
            lines = block.strip().split('\n')
            if len(lines) >= 3 and '-->' in lines[1]:
                time_line = lines[1]
                text_content = '\n'.join(lines[2:])
                
                new_start = parse_srt_time(time_line.split('--')[0].strip())
                new_end = parse_srt_time(time_line.split('--')[1].strip())
                
                entries.append(SrtEntry(
                    index=len(entries) + 1,
                    start_time=new_start,
                    end_time=new_end,
                    text=text_content
                ))
    except Exception as e:
        pass
    
    return entries


def concat_srt_files(srt_files: List[str], output_path: str,
                       time_offset: float = 0.0) -> bool:
    """
    合并多个 SRT 文件，处理时间偏移
    
    Args:
        srt_files: SRT 文件路径列表（按顺序）
        output_path: 输出路径
        time_offset: 起始时间偏移(秒)
        
    Returns:
        是否成功
    """
    all_entries: List[SrtEntry] = []
    current_offset = time_offset
    idx = 1
    
    for srt_path in srt_files:
        file_start = current_offset
        entries = parse_srt_file(srt_path)
        
        for entry in entries:
            new_entry = SrtEntry(
                index=idx,
                start_time=file_start + entry.start_time,
                end_time=file_start + entry.end_time - entry.start_time,
                text=entry.text
            )
            all_entries.append(new_entry)
            idx += 1
        
        # 更新偏移：使用该文件的最后一个时间点
        if entries:
            last = entries[-1]
            current_offset = file_start + (last.end_time - last.start_time)
    
    if not all_entries:
        return False
    
    with open(output_path, 'w', encoding='utf-8') as f:
        for entry in all_entries:
            f.write(f"{entry.index}\n"
                     f"{seconds_to_srt_time(entry.start_time)} --> {seconds_to_srt_time(entry.end_time)}\n"
                     f"{entry.text}\n\n")
    
    return True
