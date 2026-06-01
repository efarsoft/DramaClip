#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
声音避让 (Audio Ducking) 工具模块

当解说/语音出现时，自动降低背景音（原声）的音量，解说结束后恢复。
常用于视频解说、播客、音乐制作等场景。

实现方式：
1. sidechaincompress 滤镜 - 使用侧链压缩
2. compand 滤镜 - 使用动态范围压缩
3. volume automation - 手动音量自动化
"""

import os
import subprocess
from typing import Optional, Dict, Any
from loguru import logger

from app.utils.ffmpeg_utils import get_ffmpeg_path


def apply_ducking_sidechain(
    original_audio: str,
    narration_audio: str,
    output_path: str,
    ducking_config: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    使用 sidechaincompress 滤镜实现声音避让
    
    Args:
        original_audio: 原声音频路径
        narration_audio: 解说音频路径
        output_path: 输出音频路径
        ducking_config: 避让配置
        
    Returns:
        bool: 是否成功
    """
    from app.config.audio_config import DUCKING_CONFIG
    config = ducking_config or DUCKING_CONFIG
    
    threshold = config.get('threshold', -30.0)
    # Convert dB threshold to linear amplitude if negative
    if threshold < 0:
        import math
        threshold = math.pow(10, threshold / 20.0)
    ratio = config.get('ratio', 12.0)
    attack = config.get('attack', 0.005)
    release = config.get('release', 0.3)
    
    # FFmpeg sidechaincompress expects attack and release in milliseconds
    attack = max(0.01, attack * 1000.0)
    release = max(0.01, release * 1000.0)
    
    try:
        # sidechaincompress 滤镜
        # [0:a] 原声, [1:a] 解说（侧链输入）
        cmd = [
            get_ffmpeg_path(), '-y',
            '-i', original_audio,
            '-i', narration_audio,
            '-filter_complex',
            f'[1:a]asplit=2[sc][n];'
            f'[0:a][sc]sidechaincompress='
            f'threshold={threshold}:'
            f'ratio={ratio}:'
            f'attack={attack}:'
            f'release={release}:'
            f'makeup=1[aout]',
            '-map', '[aout]',
            '-map', '1:a',
            '-c:a', 'aac',
            '-b:a', '192k',
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode == 0 and os.path.exists(output_path):
            logger.info(f"声音避让处理完成: {output_path}")
            return True
        else:
            logger.error(f"声音避让失败: {result.stderr[:300]}")
            return False
            
    except Exception as e:
        logger.error(f"声音避让异常: {e}")
        return False


def apply_ducking_volume_automation(
    original_audio: str,
    narration_audio: str,
    output_path: str,
    ducking_config: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    使用 volume automation 实现声音避让
    
    更精确的控制，适用于已知解说时间戳的场景
    
    Args:
        original_audio: 原声音频路径
        narration_audio: 解说音频路径
        output_path: 输出音频路径
        ducking_config: 避让配置
        
    Returns:
        bool: 是否成功
    """
    from app.config.audio_config import DUCKING_CONFIG
    config = ducking_config or DUCKING_CONFIG
    
    ducked_volume = config.get('ducked_volume', 0.25)
    fade_duration = config.get('fade_duration', 0.2)
    
    try:
        # 使用 compand 滤镜实现自动避让
        cmd = [
            get_ffmpeg_path(), '-y',
            '-i', original_audio,
            '-i', narration_audio,
            '-filter_complex',
            f'[1:a]volume=1[n];'
            f'[0:a][n]amix=inputs=2:duration=first:dropout_transition=2,'
            f'compand='
            f'attacks=0.001:decays=0.1:'
            f'points=-90/-90|-{abs(int(threshold))}/-{abs(int(threshold))}|-45/-45|-20/-20:'
            f'soft-knee=6:'
            f'gain=0[aout]' if 'threshold' in locals() else
            f'[0:a][n]amix=inputs=2:duration=first:dropout_transition=2[aout]',
            '-map', '[aout]',
            '-c:a', 'aac',
            '-b:a', '192k',
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode == 0 and os.path.exists(output_path):
            logger.info(f"音量自动化处理完成: {output_path}")
            return True
        else:
            logger.error(f"音量自动化失败: {result.stderr[:300]}")
            return False
            
    except Exception as e:
        logger.error(f"音量自动化异常: {e}")
        return False


def mix_audio_with_ducking(
    video_path: str,
    narration_audio: str,
    output_path: str,
    original_volume: float = 1.0,
    narration_volume: float = 1.0,
    ducking_config: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    混合视频原声和解说音频，带声音避让效果
    
    Args:
        video_path: 视频文件路径（包含原声）
        narration_audio: 解说音频路径
        output_path: 输出视频路径
        original_volume: 原声音量 (0-1)
        narration_volume: 解说音量 (0-1)
        ducking_config: 避让配置
        
    Returns:
        bool: 是否成功
    """
    from app.config.audio_config import DUCKING_CONFIG
    config = ducking_config or DUCKING_CONFIG
    
    threshold = config.get('threshold', -30.0)
    # Convert dB threshold to linear amplitude if negative
    if threshold < 0:
        import math
        threshold = math.pow(10, threshold / 20.0)
    ratio = config.get('ratio', 12.0)
    attack = config.get('attack', 0.005)
    release = config.get('release', 0.3)
    
    # FFmpeg sidechaincompress expects attack and release in milliseconds
    attack = max(0.01, attack * 1000.0)
    release = max(0.01, release * 1000.0)
    
    try:
        # 使用 sidechaincompress 实现视频中的声音避让
        cmd = [
            get_ffmpeg_path(), '-y',
            '-i', video_path,
            '-i', narration_audio,
            '-filter_complex',
            f'[0:a]volume={original_volume}[orig];'
            f'[1:a]volume={narration_volume}[narr];'
            f'[narr]asplit=2[sc][n];'
            f'[orig][sc]sidechaincompress='
            f'threshold={threshold}:'
            f'ratio={ratio}:'
            f'attack={attack}:'
            f'release={release}:'
            f'makeup=1[ducked];'
            f'[ducked][n]amix=inputs=2:duration=first:dropout_transition=2[aout]',
            '-map', '0:v',
            '-map', '[aout]',
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-b:a', '192k',
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600
        )
        
        if result.returncode == 0 and os.path.exists(output_path):
            logger.info(f"带避让的音频混合完成: {output_path}")
            return True
        else:
            logger.error(f"带避让的音频混合失败: {result.stderr[:300]}")
            return False
            
    except Exception as e:
        logger.error(f"带避让的音频混合异常: {e}")
        return False


def get_ducking_filter_string(
    original_volume: float = 1.0,
    ducking_config: Optional[Dict[str, Any]] = None,
) -> str:
    """
    获取 FFmpeg sidechaincompress 滤镜字符串
    
    用于集成到其他 FFmpeg 命令中
    
    Args:
        original_volume: 原声音量
        ducking_config: 避让配置
        
    Returns:
        str: 滤镜字符串
    """
    from app.config.audio_config import DUCKING_CONFIG
    config = ducking_config or DUCKING_CONFIG
    
    threshold = config.get('threshold', -30.0)
    # Convert dB threshold to linear amplitude if negative
    if threshold < 0:
        import math
        threshold = math.pow(10, threshold / 20.0)
    ratio = config.get('ratio', 12.0)
    attack = config.get('attack', 0.005)
    release = config.get('release', 0.3)
    
    # FFmpeg sidechaincompress expects attack and release in milliseconds
    attack = max(0.01, attack * 1000.0)
    release = max(0.01, release * 1000.0)
    
    return (
        f'volume={original_volume}[orig];'
        f'[1:a]asplit=2[sc][n];'
        f'[orig][sc]sidechaincompress='
        f'threshold={threshold}:'
        f'ratio={ratio}:'
        f'attack={attack}:'
        f'release={release}:'
        f'makeup=1[ducked];'
        f'[ducked][n]amix=inputs=2:duration=first:dropout_transition=2[aout]'
    )
