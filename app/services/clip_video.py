"""向后兼容 - 已迁移到 app.services.clip.clip_video"""
from app.services.clip.clip_video import *  # noqa: F401,F403
from app.services.clip.clip_video import (  # noqa: F401
    clip_video_unified_multi,
    parse_timestamp, calculate_end_time,
    check_hardware_acceleration, get_safe_encoder_config,
    build_ffmpeg_command, execute_ffmpeg_with_fallback,
)
